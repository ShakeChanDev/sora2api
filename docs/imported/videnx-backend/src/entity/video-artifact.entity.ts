import { Entity, Column, PrimaryGeneratedColumn, Index } from 'typeorm';
import { Base } from '../providers/template/base.entity';
import { TaskGenerateType } from './task-group.entity';
export enum ArtifactStatus {
  PENDING = 'PENDING',
  PROCESSING = 'PROCESSING',
  PAUSED = 'PAUSED',
  COMPLETED = 'COMPLETED',
  FAILED = 'FAILED',
}

export enum VideoArtifactGrade {
  S = 'S',
  A = 'A',
  B = 'B',
}
export enum VideoArtifactType {
  VIDEO = 'video',
  IMAGE = 'image',
}

@Entity('video_artifacts')
@Index(['taskId'])
@Index(['platform', 'platformTaskId'])
@Index(['status'])
@Index(['operatorUserId', 'generateType'])
export class VideoArtifact extends Base {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ comment: '关联任务ID' })
  taskId: string;

  @Column({ comment: '关联任务组ID', nullable: true })
  groupId: string;

  @Column({
    type: 'varchar',
    length: 20,
    default: TaskGenerateType.IMAGE,
    comment: '生成类型(image/remix)',
  })
  generateType: TaskGenerateType;

  @Column({ length: 20, comment: '生成平台: sora, midjourney', nullable: true })
  platform: string;

  @Column({ length: 64, comment: '平台侧任务ID', nullable: true })
  platformTaskId: string;

  @Column({ type: 'int', default: 0, comment: '生成尝试次数(创建请求次数)' })
  generationAttempt: number;

  @Column({ type: 'varchar', length: 36, nullable: true, comment: '退积分流水ID(幂等标记)' })
  refundRecordId?: string | null;

  @Column({
    type: 'varchar',
    length: 20,
    default: ArtifactStatus.PENDING,
    comment: '状态'
  })
  status: ArtifactStatus;

  @Column('text', { nullable: true, comment: '完成版链接 (去水印)' })
  finishedUrl: string;

  @Column('text', { nullable: true, comment: '封面图' })
  coverUrl: string;

  @Column('timestamp', { nullable: true, comment: '提交给平台的时间' })
  videoApplyAt: Date;

  @Column('timestamp', { nullable: true, comment: '视频生成完成时间' })
  videoCreatedAt: Date;

  @Column('text', { nullable: true, comment: '错误信息' })
  errorMsg: string;

  @Column({
    type: 'varchar',
    length: 2,
    nullable: true,
    comment: '评分'
  })
  grade: VideoArtifactGrade;

  @Column({ type: 'varchar', length: 36, nullable: true, comment: '操作者用户ID' })
  operatorUserId?: string;

}
