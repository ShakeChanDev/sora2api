import { Injectable, Logger, Inject } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { TaskGroup, TaskGroupStage } from '@/src/entity/task-group.entity';
import { ArtifactStatus, VideoArtifact } from '@/src/entity/video-artifact.entity';
import { IVideoTaskRunner } from './video.runner.interface';
import { PureEngineService } from '@/src/providers/template/engine.service';
import { USER_POINTS_COST_MAP, UserPointsOperationType } from '@/src/entity/user-points-record.entity';
import { UserService } from '@/src/model/user.service';

@Injectable()
export class DispatchVideoRunner extends PureEngineService implements IVideoTaskRunner {
  protected readonly logger = new Logger(DispatchVideoRunner.name);

  @InjectRepository(TaskGroup) 
  private readonly groupRepo: Repository<TaskGroup>

  @InjectRepository(VideoArtifact) 
  private readonly artifactRepo: Repository<VideoArtifact>

  @Inject()
  private readonly userService: UserService;

  /**
   * 调度待生成的任务组创建产物
   */
  async run(): Promise<void> {
    const groups = await this.groupRepo.find({
      where: { stage: TaskGroupStage.QUEUED },
    });

    await Promise.all(groups.map(group => this.dispatchGroup(group)));
  }

  /**
   * 为指定任务组创建缺失的产物并扣减积分
   */
  private async dispatchGroup(group: TaskGroup) {
    const existingCount = await this.artifactRepo.count({
      where: { groupId: group.id }
    });

    const targetCount = group.targetCount || 1;
    const needed = targetCount - existingCount;

    if (needed <= 0) {
      if (group.stage === TaskGroupStage.QUEUED) {
        await this.groupRepo.update(group.id, { stage: TaskGroupStage.GENERATING });
      }
      return;
    }

    if (!group.operatorUserId) {
      await this.groupRepo.update(group.id, { stage: TaskGroupStage.FAILED, error: '缺少操作者用户ID' });
      return;
    }

    const unitCost = USER_POINTS_COST_MAP[UserPointsOperationType.TASK_CONSUME] || 2;
    const cost = unitCost * needed;
    try {
      await this.userService.changePoints({
        userId: group.operatorUserId,
        delta: -cost,
        operationType: UserPointsOperationType.TASK_CONSUME,
        reason: '创建任务产物扣减',
        evidenceType: 'task_group',
        evidenceId: group.id,
      });
    } catch (error) {
      const msg = String(error?.message || '积分扣减失败');
      await this.groupRepo.update(group.id, { stage: TaskGroupStage.FAILED, error: msg });
      return;
    }

    const artifacts: VideoArtifact[] = [];
    for (let i = 0; i < needed; i++) {
      const artifact = this.artifactRepo.create({
        taskId: group.taskId,
        groupId: group.id,
        status: ArtifactStatus.PENDING,
        generateType: group.generateType,
        operatorUserId: group.operatorUserId,
      });
      artifacts.push(artifact);
    }

    await this.artifactRepo.save(artifacts);

    if (group.stage === TaskGroupStage.QUEUED) {
      await this.groupRepo.update(group.id, { stage: TaskGroupStage.GENERATING });
    }

    this.logger.log(`Dispatched group ${group.id}, created ${needed} artifacts`);
  }
}
