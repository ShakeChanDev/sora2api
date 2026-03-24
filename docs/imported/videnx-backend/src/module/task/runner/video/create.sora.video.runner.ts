import { Injectable, Logger, Inject } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, IsNull, In, DataSource } from 'typeorm';
import { ArtifactStatus, VideoArtifact } from '@/src/entity/video-artifact.entity';
import { TaskGenerateType, TaskGroup } from '@/src/entity/task-group.entity';
import { IVideoTaskRunner } from './video.runner.interface';
import { PureEngineService } from '@/src/providers/template/engine.service';
import { UserService } from '@/src/model/user.service';
import { USER_POINTS_COST_MAP, UserPointsOperationType } from '@/src/entity/user-points-record.entity';
import {
  VideoProvider,
  VideoCreateReq,
  CreateResult,
} from '@/src/module/task/provider/video.provider';

@Injectable()
export class CreateSoraVideoRunner extends PureEngineService implements IVideoTaskRunner {
  protected readonly logger = new Logger(CreateSoraVideoRunner.name);

  @InjectRepository(VideoArtifact)
  private readonly artifactRepo: Repository<VideoArtifact>;

  @InjectRepository(TaskGroup)
  private readonly groupRepo: Repository<TaskGroup>;

  @Inject()
  private readonly dataSource: DataSource;

  @Inject()
  private readonly userService: UserService;

  @Inject()
  private readonly videoProvider: VideoProvider;

  async run(): Promise<void> {
    const artifacts = await this.artifactRepo.find({
      where: {
        status: ArtifactStatus.PENDING,
        platformTaskId: IsNull(),
      },
      order: {
        groupId: 'ASC',
      },
      take: 20,
    });

    if (artifacts.length === 0) return;

    // 2. Group by groupId
    const artifactsByGroup: Record<string, VideoArtifact[]> = {};
    const groupIds = new Set<string>();

    for (const artifact of artifacts) {
      if (!artifactsByGroup[artifact.groupId]) {
        artifactsByGroup[artifact.groupId] = [];
        groupIds.add(artifact.groupId);
      }
      artifactsByGroup[artifact.groupId].push(artifact);
    }

    // 3. Process each group concurrently
    await Promise.all(Array.from(groupIds).map(async (groupId) => this.processGroupBatch(groupId, artifactsByGroup[groupId])));
  }

  private async processGroupBatch(groupId: string, artifacts: VideoArtifact[]) {
    // 0. 获取任务组信息
    const group = await this.groupRepo.findOne({ where: { id: groupId } });
    if (!group) return;

    const artifactIds = artifacts.map((a) => a.id);

    try {
      // 1. 预锁定所有任务状态为处理中
      await this.artifactRepo.update(
        { id: In(artifactIds) },
        { status: ArtifactStatus.PROCESSING }
      );

      for (const artifact of artifacts) {
        const currentAttempt = Number(artifact.generationAttempt || 0) || 0;
        if (currentAttempt >= this.videoProvider.maxAttempts) {
          await this.handleCreateAttemptFailure(artifact, currentAttempt, '已达到最大重试次数', '三方平台任务失败退积分');
          continue;
        }

        const nextAttempt = currentAttempt + 1;

        try {
          const createResult = await this.requestPlatformTask(group, currentAttempt);
          await this.artifactRepo.update(
            { id: artifact.id },
            {
              platform: createResult.platform,
              platformTaskId: createResult.platformTaskId,
              videoApplyAt: new Date(),
              status: ArtifactStatus.PROCESSING,
              generationAttempt: nextAttempt,
            }
          );
        } catch (e: any) {
          const msg = String(e?.message || '三方平台创建任务失败');
          if (msg.includes('缺少 remix')) {
            await this.artifactRepo.update(
              { id: artifact.id },
              { status: ArtifactStatus.FAILED, errorMsg: msg }
            );
            continue;
          }

          await this.handleCreateAttemptFailure(artifact, nextAttempt, msg, '三方平台任务失败退积分');
        }
      }

    } catch (error) {
      this.getEngine('logger').error(`Group batch failed for ${groupId}`, error);
    } finally {
      // 统一回滚未处理的所有任务
      const updateEffect = await this.artifactRepo.update(
        { id: In(artifactIds), status: ArtifactStatus.PROCESSING, platformTaskId: IsNull() },
        { status: ArtifactStatus.PENDING }
      );
      (updateEffect.affected > 0) && this.getEngine('logger').warn(`Rollback ${updateEffect.affected} artifacts for group ${groupId}`);
    }
  }

  private async requestPlatformTask(group: TaskGroup, attempt: number): Promise<CreateResult> {
    // 根据尝试次数获取供应商
    const providerType = this.videoProvider.getProviderByAttempt(attempt);
    this.logger.log(`${group.taskId} 使用供应商: ${providerType} (尝试次数: ${attempt})`);

    // 从配置获取时长
    const duration = group.config?.duration;

    // 构建请求
    const req: VideoCreateReq = {
      prompt: group.prompt,
      duration,
    };

    if (group.generateType === TaskGenerateType.REMIX) {
      const remix = Array.isArray(group.reference)
        ? group.reference.find((r) => r?.type === 'remix')?.url || group.reference[0]?.url
        : undefined;

      if (!remix) {
        throw new Error('缺少 remix 二创地址/ID');
      }

      req.remixUrl = remix;
    } else {
      const referenceImageUrl = Array.isArray(group.reference)
        ? group.reference.find((r) => r?.type === 'image')?.url || group.reference[0]?.url
        : undefined;

      req.imageUrl = referenceImageUrl;
    }

    const result = await this.videoProvider.create(req, providerType);
    if (!result.platformTaskId) throw new Error('三方平台创建任务失败');
    return result;
  }

  /**
   * 处理创建平台任务失败：未达上限则回退为待处理，达到上限则标记失败并按 Artifact 退积分（幂等）。
   */
  private async handleCreateAttemptFailure(
    artifact: VideoArtifact,
    attemptToRecord: number,
    msg: string,
    refundReason: string,
  ) {
    if (attemptToRecord >= this.videoProvider.maxAttempts) {
      await this.dataSource.transaction(async (manager) => {
        const artifactRepo = manager.getRepository(VideoArtifact);

        const locked = await artifactRepo
          .createQueryBuilder('a')
          .setLock('pessimistic_write')
          .where('a.id = :id', { id: artifact.id })
          .getOne();

        if (!locked) return;

        await artifactRepo.update(
          { id: locked.id },
          {
            status: ArtifactStatus.FAILED,
            errorMsg: `${msg}(已重试${attemptToRecord}/${this.videoProvider.maxAttempts})`,
            platformTaskId: null,
            videoApplyAt: null,
            generationAttempt: attemptToRecord,
          },
        );

        const operatorUserId = locked.operatorUserId;
        if (!operatorUserId) return;
        if (locked.refundRecordId) return;

        const refundPoints = USER_POINTS_COST_MAP[UserPointsOperationType.TASK_CONSUME] || 0;
        if (!refundPoints) return;

        const { record } = await this.userService.changePoints(
          {
            userId: operatorUserId,
            delta: refundPoints,
            operationType: UserPointsOperationType.TASK_REFUND,
            reason: refundReason || '退积分',
            evidenceType: 'artifact',
            evidenceId: locked.id,
            operatorUserId: operatorUserId,
          },
          manager,
        );

        await artifactRepo.update({ id: locked.id }, { refundRecordId: record.id });
      });
      this.getEngine('logger').warn(`任务${artifact.id} 重试失败，回滚积分`);
      return;
    }

    await this.artifactRepo.update(
      { id: artifact.id },
      {
        status: ArtifactStatus.PENDING,
        errorMsg: `${msg}(准备重试${attemptToRecord + 1}/${this.videoProvider.maxAttempts})`,
        platformTaskId: null,
        videoApplyAt: null,
        generationAttempt: attemptToRecord,
      },
    );
  }
}
