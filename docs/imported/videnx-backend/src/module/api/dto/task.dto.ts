import { BaseSuccessResponseDto } from './base.dto';
import { Task } from '@/src/entity/task.entity';
import { TaskGroup } from '@/src/entity/task-group.entity';
import { VideoArtifact } from '@/src/entity/video-artifact.entity';
import { ApiExtraModels, ApiProperty, PickType, getSchemaPath } from '@nestjs/swagger';
import { Prompt } from '@/src/entity/prompt.entity';
import { TaskGenerateType, TaskPayloadConfig, TaskType } from '@/src/entity/task.entity';
import type { TaskPayload } from '@/src/entity/task.entity';

export class TaskPayloadReferenceDto {
  @ApiProperty()
  url: string;

  @ApiProperty()
  type: string;
}

export class TaskPayloadBaseDto {
  @ApiProperty({ enum: Object.values(TaskGenerateType), required: false, description: '视频生成类型，不传则从任务类型推断' })
  type?: TaskGenerateType;

  @ApiProperty({ required: false, type: [String] })
  promptlistKey?: string[];

  @ApiProperty({ required: false, type: String })
  language?: string;

  @ApiProperty({ required: false })
  prompt?: string;

  @ApiProperty({ required: false, nullable: true, type: TaskPayloadConfig })
  config?: TaskPayloadConfig | null;

  @ApiProperty({ required: false, nullable: true, type: [TaskPayloadReferenceDto] })
  reference?: TaskPayloadReferenceDto[] | null;

  @ApiProperty({ required: false })
  count?: number;
}

export class AiGroupTaskPayloadDto extends TaskPayloadBaseDto {
  @ApiProperty({ enum: [TaskGenerateType.IMAGE], required: false })
  type?: TaskGenerateType.IMAGE;

  @ApiProperty({ required: false })
  groupCount?: number;

  @ApiProperty({ required: false, description: '关联的分析记录ID（复刻任务使用）' })
  analysisId?: string;
}

export class ImageTaskPayloadDto extends TaskPayloadBaseDto {
  @ApiProperty({ enum: [TaskGenerateType.IMAGE], required: false })
  type?: TaskGenerateType.IMAGE;
}

export class RemixTaskPayloadDto extends TaskPayloadBaseDto {
  @ApiProperty({ enum: [TaskGenerateType.REMIX], required: false })
  type?: TaskGenerateType.REMIX;

  @ApiProperty({ required: false })
  linkUrl?: string;
}

@ApiExtraModels(
  TaskPayloadReferenceDto,
  TaskPayloadConfig,
  TaskPayloadBaseDto,
  AiGroupTaskPayloadDto,
  ImageTaskPayloadDto,
  RemixTaskPayloadDto,
)
export class CreateTaskBodyDto {
  /** 任务类型 */
  @ApiProperty({ enum: Object.values(TaskType), description: '任务类型' })
  type: TaskType;

  /** 自定义任务名称 */
  @ApiProperty({ required: false })
  taskName?: string;

  /** 任务载荷 */
  @ApiProperty({
    oneOf: [
      { $ref: getSchemaPath(ImageTaskPayloadDto) },
      { $ref: getSchemaPath(RemixTaskPayloadDto) },
      { $ref: getSchemaPath(AiGroupTaskPayloadDto) },
    ],
  })
  payload: TaskPayload;
}

export class TaskDetailDataDto {
  /** 任务 */
  task: Task;

  /** 分组列表 */
  groups: TaskGroup[];

  /** 产物列表 */
  artifacts: VideoArtifact[];
}

export class TaskDetailResponseDto extends BaseSuccessResponseDto {
  /** 响应数据 */
  declare data: TaskDetailDataDto;
}

export class CreateTaskResponseDto extends BaseSuccessResponseDto {
  /** 响应数据 */
  declare data: Task;
}

export enum ConfirmTaskGroupAction {
  CHECK = 'check',
  DELETE = 'delete',
  CHANGE = 'change',
}

export class ConfirmTaskGroupMapItemDto {
  @ApiProperty({ enum: ConfirmTaskGroupAction })
  action: ConfirmTaskGroupAction;

  @ApiProperty({ required: false, type: TaskGroup })
  info?: TaskGroup;
}

@ApiExtraModels(ConfirmTaskGroupMapItemDto, TaskGroup)
export class ConfirmTaskGroupsBodyDto {
  /** 任务ID */
  taskId: string;

  /** 分组确认/变更映射，key 为组标识（现有组ID或新组临时键），value 为 { action: check|delete|change, info } */
  @ApiProperty({
    type: 'object',
    additionalProperties: {
      $ref: getSchemaPath(ConfirmTaskGroupMapItemDto),
    },
  })
  groupMap: Record<string, ConfirmTaskGroupMapItemDto>;
}

export class ConfirmTaskGroupsDataDto {
  /** 总数量 */
  total: number;

  /** 已确认数量 */
  confirmedCount: number;

  /** 已移除数量 */
  removedCount: number;
}

export class ConfirmTaskGroupsResponseDto extends BaseSuccessResponseDto {
  /** 响应数据 */
  declare data: ConfirmTaskGroupsDataDto;
}

export class PromptOptionDto extends PickType(Prompt, ['id', 'name', 'category', 'type', 'desc'] as const) {}

export class PromptOptionDataDto {
  /** 列表 */
  items: PromptOptionDto[];
}

export class PromptOptionResponseDto extends BaseSuccessResponseDto {
  /** 响应数据 */
  declare data: PromptOptionDataDto;
}

export class TaskListQueryDto {
  /** 页码 */
  page?: number;

  /** 每页条数 */
  pageSize?: number;
}

export class TaskListItemDto {
  /** 任务 */
  task: Task;

  /** 分组列表 */
  groups: TaskGroup[];

  /** 产物列表 */
  artifacts: VideoArtifact[];
}

export class TaskListDataDto {
  /** 页码 */
  page: number;

  /** 每页条数 */
  pageSize: number;

  /** 总数 */
  total: number;

  /** 列表 */
  items: TaskListItemDto[];
}

export class TaskListResponseDto extends BaseSuccessResponseDto {
  /** 响应数据 */
  declare data: TaskListDataDto;
}
