import { Injectable, Logger, Inject } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, In, Not, IsNull, LessThan } from 'typeorm';
import { ArtifactStatus, VideoArtifact } from '@/src/entity/video-artifact.entity';
import { TaskGroup, TaskGroupStage } from '@/src/entity/task-group.entity';
import { IVideoTaskRunner } from './video.runner.interface';
import { PureEngineService } from '@/src/providers/template/engine.service';
import { VideoProvider, ProviderType } from '@/src/module/task/provider/video.provider';

@Injectable()
export class PollingSoraVideoRunner extends PureEngineService implements IVideoTaskRunner {
  protected readonly logger = new Logger(PollingSoraVideoRunner.name);
  private readonly pollIntervalMs = 2 * 60 * 1000;
  private readonly attemptTimeoutMs = 30 * 60 * 1000;

  @InjectRepository(VideoArtifact)
  private readonly artifactRepo: Repository<VideoArtifact>;

  @InjectRepository(TaskGroup)
  private readonly groupRepo: Repository<TaskGroup>;

  @Inject()
  private readonly videoProvider: VideoProvider;

  async run(): Promise<void> {
    // 1. 获取 GENERATING 状态的 Artifacts，且 videoApplyAt 超过 2 分钟
    const twoMinutesAgo = new Date(Date.now() - this.pollIntervalMs);
    
    const artifacts = await this.artifactRepo.find({
      where: { 
          platformTaskId: Not(IsNull()),
          finishedUrl: IsNull(),
          videoApplyAt: LessThan(twoMinutesAgo),
          status: ArtifactStatus.PROCESSING,
      },
    });

    if (artifacts.length === 0) return;

    const artifactsByGroupId: Record<string, VideoArtifact[]> = {};
    for (const artifact of artifacts) {
        if (artifact.groupId) {
            if (!artifactsByGroupId[artifact.groupId]) {
                artifactsByGroupId[artifact.groupId] = [];
            }
            artifactsByGroupId[artifact.groupId].push(artifact);
        }
    }

    await Promise.all(artifacts.map((artifact) => this.pollArtifact(artifact)));

    await Promise.all(
      Object.keys(artifactsByGroupId).map(groupId => 
        this.checkGroupCompletion(groupId)
      )
    );

  }

  private async pollArtifact(artifact: VideoArtifact) {
    try {
      const taskId = artifact.platformTaskId;
      if (!taskId) return;

      // 根据 platform 字段获取对应的 Provider
      const platform = artifact.platform as ProviderType;
      const task = await this.videoProvider.poll(taskId, platform);

      if (!task) {
        const startedAt = artifact.videoApplyAt ? new Date(artifact.videoApplyAt).getTime() : 0;
        if (startedAt && Date.now() - startedAt >= this.attemptTimeoutMs) {
          await this.handleAttemptFailure(artifact, `三方平台查询超时(> ${Math.floor(this.attemptTimeoutMs / 60000)}min)`);
        }
        return;
      }

      if (task.status === 'failed') {
        await this.handleAttemptFailure(artifact, `三方平台任务失败: ${task.errorMsg || task.status}`);
        return;
      }

      if (task.videoUrl) {
        const completedAt = new Date();
        await this.artifactRepo.update(
          { id: artifact.id },
          {
            finishedUrl: task.videoUrl,
            status: ArtifactStatus.COMPLETED,
            videoCreatedAt: completedAt,
          }
        );
        return;
      }
    } catch (error) {
      this.logger.error(`Polling failed for artifact ${artifact.id}`, error);
    }
  }

  /**
   * 处理三方平台任务失败/超时：回退为待创建状态，交给创建 Runner 决定是否退积分与终止。
   */
  private async handleAttemptFailure(artifact: VideoArtifact, msg: string) {
    const attempt = Number(artifact.generationAttempt || 0) || 0;
    const errorMsg =
      attempt >= this.videoProvider.maxAttempts
        ? `${msg}(已达到重试上限${attempt}/${this.videoProvider.maxAttempts})`
        : `${msg}(准备重试${attempt + 1}/${this.videoProvider.maxAttempts})`;

    await this.artifactRepo.update(
      { id: artifact.id },
      {
        status: ArtifactStatus.PENDING,
        errorMsg,
        platformTaskId: null,
        videoApplyAt: null,
      }
    );
  }

  private async checkGroupCompletion(groupId: string) {
      if (!groupId) return;

      // 检查该组下是否还有未完成的 Artifacts
      const pendingCount = await this.artifactRepo.count({
          where: { 
              groupId: groupId,
              status: In([
                ArtifactStatus.PENDING,
                ArtifactStatus.PROCESSING,
              ]),
          }
      });

      if (pendingCount === 0) {
          // 所有都结束了，更新 Group 为 REVIEWING (等待打分)
          await this.groupRepo.update(groupId, {
              stage: TaskGroupStage.REVIEWING
          });
      }
  }
}
