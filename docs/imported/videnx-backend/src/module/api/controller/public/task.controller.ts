import { Controller, Post, Body, Get, Param, Req, Query, Inject, HttpStatus } from '@nestjs/common';
import { WebError } from '@/src/common/error/web.error';
import { InjectRepository } from '@nestjs/typeorm';
import { Task } from '@/src/entity/task.entity';
import { TaskGroup } from '@/src/entity/task-group.entity';
import { VideoArtifact } from '@/src/entity/video-artifact.entity';
import { In, Repository } from 'typeorm';
import BaseController from '@/src/providers/template/base.controller';
import { ApiBody, ApiOkResponse, ApiOperation, ApiParam, ApiTags } from '@nestjs/swagger';
import type { Request } from 'express';
import {
  ConfirmTaskGroupsBodyDto,
  ConfirmTaskGroupsResponseDto,
  CreateTaskBodyDto,
  CreateTaskResponseDto,
  TaskDetailResponseDto,
  TaskListQueryDto,
  TaskListResponseDto,
} from '../../dto/task.dto.js';
import { TaskModelService } from '@/src/module/api/services/task.service';

@Controller('task')
@ApiTags('Task')
export class TaskController extends BaseController {
  @InjectRepository(Task)
  protected readonly repository: Repository<Task>;

  @InjectRepository(TaskGroup)
  private readonly groupRepo: Repository<TaskGroup>;

  @InjectRepository(VideoArtifact)
  private readonly artifactRepo: Repository<VideoArtifact>;

  @Inject()
  private readonly taskService: TaskModelService;

  @Get('list')
  @ApiOperation({ summary: '获取任务列表' })
  @ApiOkResponse({ type: TaskListResponseDto })
  async list(@Req() req: Request, @Query() query: TaskListQueryDto) {
    const operatorUserId = (req as any).auth?.sub;
    if (!operatorUserId) throw new WebError('Unauthorized', HttpStatus.UNAUTHORIZED);

    const page = Math.max(1, Number(query.page || 1));
    const pageSize = Math.min(100, Math.max(1, Number(query.pageSize || 20)));

    const [tasks, total] = await this.repository.findAndCount({
      where: { operatorUserId },
      order: { createdAt: 'DESC' },
      skip: (page - 1) * pageSize,
      take: pageSize,
    });

    const taskIds = tasks.map((t) => t.id);
    const groups = taskIds.length
      ? await this.groupRepo.find({
          where: { taskId: In(taskIds) },
          order: { createdAt: 'ASC' },
        })
      : [];

    const artifacts = taskIds.length
      ? await this.artifactRepo.find({
          where: { taskId: In(taskIds) },
          order: { createdAt: 'ASC' },
        })
      : [];

    const groupsByTaskId = new Map<string, TaskGroup[]>();
    for (const g of groups) {
      const list = groupsByTaskId.get(g.taskId) || [];
      list.push(g);
      groupsByTaskId.set(g.taskId, list);
    }

    const artifactsByTaskId = new Map<string, VideoArtifact[]>();
    for (const a of artifacts) {
      const list = artifactsByTaskId.get(a.taskId) || [];
      list.push(a);
      artifactsByTaskId.set(a.taskId, list);
    }

    return this.baseSuccess({
      page,
      pageSize,
      total,
      items: tasks.map((task) => ({
        task,
        groups: groupsByTaskId.get(task.id) || [],
        artifacts: artifactsByTaskId.get(task.id) || [],
      })),
    });
  }

  @Get(':id')
  @ApiOperation({ summary: '获取任务详情' })
  @ApiParam({ name: 'id', description: '任务ID' })
  @ApiOkResponse({ type: TaskDetailResponseDto })
  async getOne(@Param('id') id: string) {
    const task = await this.repository.findOne({ where: { id } });
    if (!task) throw new WebError('Task not found', HttpStatus.NOT_FOUND);

    const groups = await this.groupRepo.find({
      where: { taskId: id },
      order: { createdAt: 'ASC' },
    });

    const artifacts = await this.artifactRepo.find({
      where: { taskId: id },
      order: { createdAt: 'ASC' },
    });

    return this.baseSuccess({ task, groups, artifacts });
  }

  @Post('create')
  @ApiOperation({ summary: '创建任务' })
  @ApiBody({ type: CreateTaskBodyDto })
  @ApiOkResponse({ type: CreateTaskResponseDto })
  async create(@Req() req: Request, @Body() body: CreateTaskBodyDto) {
    const operatorUserId = (req as any).auth?.sub;
    const task = await this.taskService.createTask({
      operatorUserId,
      type: body.type,
      taskName: body.taskName,
      payload: body.payload,
    });
    return this.baseSuccess(task);
  }

  @Post('groups/confirm')
  @ApiOperation({ summary: '确认 AI 分组' })
  @ApiBody({ type: ConfirmTaskGroupsBodyDto })
  @ApiOkResponse({ type: ConfirmTaskGroupsResponseDto })
  async confirmGroups(@Req() req: Request, @Body() body: ConfirmTaskGroupsBodyDto) {
    const operatorUserId = (req as any).auth?.sub;
    if (!body?.taskId) throw new WebError('taskId 不能为空', HttpStatus.BAD_REQUEST);
    const task = await this.repository.findOne({ where: { id: body.taskId, operatorUserId } });
    if (!task) throw new WebError('Task not found', HttpStatus.NOT_FOUND);
    if (!body?.groupMap) throw new WebError('groupMap 不能为空', HttpStatus.BAD_REQUEST);

    const data = await this.taskService.confirmTaskGroups({ task, groupMap: body.groupMap });
    return this.baseSuccess(data);
  }
}
