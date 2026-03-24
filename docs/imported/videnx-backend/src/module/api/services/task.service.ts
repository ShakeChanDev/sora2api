import { Injectable, Inject, HttpStatus } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import dayjs from 'dayjs';
import { Repository } from 'typeorm';
import { Task, TaskPayload, TaskStatus, TaskType } from '@/src/entity/task.entity';
import { TaskGroup, TaskGroupStage, TaskGenerateType } from '@/src/entity/task-group.entity';
import { UserPointsOperationType } from '@/src/entity/user-points-record.entity';
import { UserService } from '@/src/model/user.service';
import { WebError } from '@/src/common/error/web.error';


@Injectable()
export class TaskModelService {
  @InjectRepository(Task)
  private readonly taskRepo: Repository<Task>;

  @InjectRepository(TaskGroup)
  private readonly groupRepo: Repository<TaskGroup>;

  @Inject()
  private readonly userService: UserService;

  async createTask(input: { operatorUserId: string; type: TaskType; taskName?: string; payload: TaskPayload }) {
    const operatorUserId = input?.operatorUserId;
    if (!operatorUserId) {
      throw new WebError('Unauthorized', HttpStatus.UNAUTHORIZED);
    }

    const type = input?.type;
    if (!type) {
      throw new WebError('type 不能为空', HttpStatus.BAD_REQUEST);
    }

    const payload = input?.payload;
    if (!payload) {
      throw new WebError('payload 不能为空', HttpStatus.BAD_REQUEST);
    }

    const baseCount = Math.max(1, Math.floor(Number(payload.count ?? 1)));
    let groupCount = 1;
    if (type === TaskType.AIGROUP || type === TaskType.REPLICATION) {
      const payloadGroupCount = Number((payload as any)?.groupCount ?? 1);
      groupCount = Math.max(1, Math.floor(payloadGroupCount || 1));
    }
    const totalCount = baseCount * groupCount;
    await this.userService.assertPointsAvailable({
      userId: operatorUserId,
      operationType: UserPointsOperationType.TASK_CONSUME,
      count: totalCount,
    });

    const prompt = input?.payload.prompt ?? '';
    const taskName =
      input?.taskName || prompt.slice(0, 10) || `Task-${dayjs().format('YYYYMMDDHHmmss')}`;

    const task = this.taskRepo.create({
      taskName,
      type: type,
      status: TaskStatus.PENDING,
      payload: input?.payload,
      operatorUserId: input?.operatorUserId,
      ...('analysisId' in payload ? { analysisId: payload.analysisId } : {}), // 仅当存在时关联分析记录
    });
    await this.taskRepo.save(task);
    return task;
  }

  async confirmTaskGroups(input: {
    task: Task;
    groupMap: Record<string, { action: 'check' | 'delete' | 'change'; info?: Partial<TaskGroup> }>;
  }) {
    const task = input.task;
    const groupMap = input.groupMap;

    if (!task.operatorUserId) {
      throw new WebError('Unauthorized', HttpStatus.UNAUTHORIZED);
    }

    const groups = await this.groupRepo.find({
      where: {
        taskId: task.id,
        operatorUserId: task.operatorUserId,
        stage: TaskGroupStage.WAITING_CONFIRM,
      },
    });

    const removedIds: string[] = [];
    const confirmedIds: string[] = [];
    const changedIds: string[] = [];
    const groupMapEntries = Object.entries(groupMap);
    const groupMapById = new Map(groups.map((g) => [g.id, g]));

    const updateTasks: Array<Promise<any>> = [];
    const newGroups: TaskGroup[] = [];
    let requiredCount = 0;

    for (const [key, entry] of groupMapEntries) {
      const action = entry?.action;
      const entity = entry?.info;
      if (!action) continue;
      const targetGroup = groupMapById.get(key) ?? (entity?.id ? groupMapById.get(entity.id) : undefined);

      // 如果没有找到 targetGroup，且 action 是 check 或 change，说明是新增的组
      if (!targetGroup && (action === 'check' || action === 'change') && entity) {
        const targetCount = Math.max(1, Math.floor(Number(entity.targetCount ?? 1)));
        requiredCount += targetCount;
        
        // 如果前端没传 generateType，从原有组中继承（或使用默认值）
        let generateType = entity.generateType;
        if (!generateType && groups.length > 0) {
          generateType = groups[0].generateType;
        }
        if (!generateType) {
          generateType = TaskGenerateType.IMAGE;
        }
        
        const newGroup = this.groupRepo.create({
          taskId: task.id,
          stage: TaskGroupStage.QUEUED,
          generateType,
          prompt: entity.prompt ?? '',
          reference: entity.reference ?? (groups.length > 0 ? groups[0].reference : null),
          config: entity.config ?? (groups.length > 0 ? groups[0].config : null),
          targetCount,
          operatorUserId: task.operatorUserId,
        });
        
        newGroups.push(newGroup);
        confirmedIds.push(key);
        continue;
      }

      switch (action) {
        case 'delete': {
          if (targetGroup) removedIds.push(targetGroup.id);
          break;
        }
        case 'check': {
          if (targetGroup) {
            const targetCount = entity?.targetCount 
              ? Math.max(1, Math.floor(Number(entity.targetCount)))
              : targetGroup.targetCount;
            
            requiredCount += targetCount;
            
            updateTasks.push(this.groupRepo.update(targetGroup.id, { 
              stage: TaskGroupStage.QUEUED,
              targetCount,
            }));
            confirmedIds.push(targetGroup.id);
          }
          break;
        }
        case 'change': {
          if (targetGroup) {
            const targetCount = Math.max(1, Math.floor(Number(entity?.targetCount ?? 1)));
            
            requiredCount += targetCount;
            
            updateTasks.push(
              this.groupRepo.update(targetGroup.id, {
                stage: TaskGroupStage.QUEUED,
                prompt: entity?.prompt ?? targetGroup.prompt,
                config: entity?.config ?? targetGroup.config,
                reference: entity?.reference ?? targetGroup.reference,
                targetCount,
              }),
            );
            changedIds.push(targetGroup.id);
          } 
          break;
        }
      }
    }

    if (requiredCount > 0) {
      await this.userService.assertPointsAvailable({
        userId: task.operatorUserId,
        operationType: UserPointsOperationType.TASK_CONSUME,
        count: requiredCount,
      });
    }

    // 执行删除操作
    if (removedIds.length) {
      await this.groupRepo.delete(removedIds);
    }

    // 执行更新操作（确认和修改）
    if (updateTasks.length) {
      await Promise.all(updateTasks);
    }

    // 保存新增的组
    if (newGroups.length) {
      await this.groupRepo.save(newGroups);
    }

    // Check if all groups are deleted, if so, mark task as COMPLETED
    const remainingCount = await this.groupRepo.count({ where: { taskId: task.id } });
    if (remainingCount === 0) {
      await this.taskRepo.update(task.id, { status: TaskStatus.COMPLETED });
    }

    return {
      total: confirmedIds.length + changedIds.length + removedIds.length,
      confirmedCount: confirmedIds.length + changedIds.length,
      removedCount: removedIds.length,
    };
  }
}
