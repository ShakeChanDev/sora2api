import { Entity, Column, PrimaryGeneratedColumn, Index } from 'typeorm';
import { Base } from '../providers/template/base.entity';
import { TaskGenerateType, TaskPayloadConfig } from './task.entity';

export { TaskGenerateType };

export enum TaskGroupStage {
  WAITING_CONFIRM = 'WAITING_CONFIRM',
  QUEUED = 'QUEUED',          // 任务分发创建
  GENERATING = 'GENERATING',  // 生成视频
  REVIEWING = 'REVIEWING',    // 评分
  FINISHED = 'FINISHED',      // 处理并完成下载
  FAILED = 'FAILED'
}


@Entity('task_groups')
@Index(['taskId'])
@Index(['stage'])
@Index(['operatorUserId'])
export class TaskGroup extends Base {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ comment: '关联任务ID' })
  taskId: string;

  @Column('varchar', { length: 20, comment: '运行阶段' })
  stage: TaskGroupStage;

  @Column({
    type: 'varchar',
    length: 20,
    default: TaskGenerateType.IMAGE,
    comment: '生成类型(image/remix)',
  })
  generateType: TaskGenerateType;

  @Column('text', { comment: '提示词' })
  prompt: string;

  @Column('json', { nullable: true, comment: '参考图/视频数组' })
  reference: any[];

  @Column('json', { nullable: true, comment: '生成参数(duration, ratio)' })
  config: TaskPayloadConfig;

  @Column('int', { default: 1, comment: '目标生成数量' })
  targetCount: number;

  @Column({ type: 'varchar', length: 36, nullable: true, comment: '操作者用户ID' })
  operatorUserId?: string;

  @Column({ type: 'text', nullable: true, comment: '错误信息' })
  error?: string;
}
