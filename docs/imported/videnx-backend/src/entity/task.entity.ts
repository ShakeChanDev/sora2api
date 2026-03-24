import { Entity, Column, PrimaryGeneratedColumn, Index } from 'typeorm';
import { Base } from '../providers/template/base.entity';

export enum TaskStatus {
  PENDING = 'PENDING',
  PROCESSING = 'PROCESSING', // 任务正在自动执行中
  PAUSED = 'PAUSED', // 任务暂停 (等待人工处理)
  COMPLETED = 'COMPLETED',
  FAILED = 'FAILED',
}

export interface TaskResult {
  artifactsCount?: number;
  [key: string]: any;
}

@Entity('tasks')
@Index(['status'])
@Index(['operatorUserId'])
@Index(['type'])
export class Task extends Base {
  @PrimaryGeneratedColumn('uuid')
  id: string; // 主键ID

  @Column({ comment: '任务名称' })
  taskName: string; // 任务名称

  @Column({
    type: 'varchar',
    length: 20,
    comment: '任务类型: image/remix/AiGroup/replication'
  })
  type: TaskType; // 任务类型

  @Column({
    type: 'varchar',
    length: 20,
    default: TaskStatus.PENDING,
    comment: '任务状态'
  })
  status: TaskStatus; // 状态

  @Column('json', { nullable: true, comment: '任务载荷: prompt, count, ratio, etc.' })
  payload: TaskPayload; // 载荷

  @Column('json', { nullable: true, comment: '任务结果统计' })
  result: TaskResult; // 结果

  @Column('text', { nullable: true, comment: '错误信息' })
  error: string; // 错误信息

  @Column({ type: 'varchar', length: 36, nullable: true, comment: '关联的分析记录ID' })
  analysisId: string;

  @Column({ type: 'varchar', length: 36, nullable: true, comment: '操作者用户ID' })
  operatorUserId?: string;
}

export enum TaskType {
  IMAGE = 'image',
  REMIX = 'remix',
  AIGROUP = 'AiGroup',
  REPLICATION = 'replication',
}

export enum TaskGenerateType {
  IMAGE = 'image',
  REMIX = 'remix'
}

export type TaskPayloadReference = {
  url: string;
  type: string;
};

export class TaskPayloadConfig {
  /** 视频时长（秒） */
  duration?: number;
  /** 画面比例，例如 portrait */
  ratio?: string;
}

export type TaskPayloadBase = {
  type?: TaskGenerateType; // 可选，默认从任务类型推断
  promptlistKey?: string[];
  language?: string;
  prompt?: string;
  config?: TaskPayloadConfig | null;
  reference?: TaskPayloadReference[] | null;
  count?: number;
};

export type AiGroupTaskPayload = TaskPayloadBase & {
  type?: TaskGenerateType.IMAGE;
  groupCount?: number;
  analysisId?: string; // 关联的分析记录ID（复刻任务使用）
};

export type ImageTaskPayload = TaskPayloadBase & {
  type?: TaskGenerateType.IMAGE;
};

export type RemixTaskPayload = TaskPayloadBase & {
  type?: TaskGenerateType.REMIX;
  linkUrl?: string;
};

export type TaskPayload = ImageTaskPayload | RemixTaskPayload | AiGroupTaskPayload;
