import { Injectable, Logger } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { PureEngineService } from '@/src/providers/template/engine.service';
import { TaskGroup, TaskGroupStage } from '@/src/entity/task-group.entity';
import { Task, TaskStatus } from '@/src/entity/task.entity';
import { ArtifactStatus, VideoArtifact } from '@/src/entity/video-artifact.entity';
import { IVideoTaskRunner } from './video.runner.interface';

@Injectable()
export class TaskCompletionRunner extends PureEngineService implements IVideoTaskRunner {
  protected readonly logger = new Logger(TaskCompletionRunner.name);

  @InjectRepository(Task)
  private readonly taskRepo: Repository<Task>;

  @InjectRepository(TaskGroup)
  private readonly groupRepo: Repository<TaskGroup>;

  @InjectRepository(VideoArtifact)
  private readonly artifactRepo: Repository<VideoArtifact>;

  async run(): Promise<void> {
    await this.checkGroupGeneration();
    await this.checkGroupCompletion();
    await this.checkTaskCompletion();
  }

  private async checkGroupGeneration() {
    // Check groups in GENERATING state
    const groups = await this.groupRepo.find({
      where: { stage: TaskGroupStage.GENERATING },
    });

    for (const group of groups) {
      const artifacts = await this.artifactRepo.find({
        where: { groupId: group.id },
      });

      if (artifacts.length === 0) continue;

      // Check if there are any pending/processing artifacts
      const hasPending = artifacts.some((a) =>
        [ArtifactStatus.PENDING, ArtifactStatus.PROCESSING].includes(a.status),
      );

      if (hasPending) continue;

      // All done, check results
      // Success if COMPLETED or has finishedUrl
      const hasSuccess = artifacts.some(
        (a) => a.status === ArtifactStatus.COMPLETED || !!a.finishedUrl,
      );

      if (hasSuccess) {
        await this.groupRepo.update(group.id, { stage: TaskGroupStage.REVIEWING });
        this.logger.log(`Group ${group.id} finished generation -> REVIEWING`);
      } else {
        // All failed
        await this.groupRepo.update(group.id, { stage: TaskGroupStage.FAILED });
        this.logger.log(`Group ${group.id} all artifacts failed -> FAILED`);
      }
    }
  }

  private async checkGroupCompletion() {
    // Check groups in REVIEWING state
    const groups = await this.groupRepo.find({
      where: { stage: TaskGroupStage.REVIEWING },
    });

    for (const group of groups) {
      const artifacts = await this.artifactRepo.find({
        where: { groupId: group.id }
      });

      if (artifacts.length === 0) continue;

      const allDone = artifacts.every(a => {
        // Condition for artifact being "Done" for the group to finish:
        // 1. FAILED
        // 2. RELEASED (Dewatermarked)
        // 3. COMPLETED + Graded B (No dewatermark needed)
        
        if (a.status === ArtifactStatus.FAILED) return true;

        if (a.finishedUrl) {
          return true
        }
        
        return false;
      });

      if (allDone) {
        await this.groupRepo.update(group.id, { stage: TaskGroupStage.FINISHED });
        this.logger.log(`Group ${group.id} finished`);
      }
    }
  }

  private async checkTaskCompletion() {
    // Check tasks in PROCESSING state
    const tasks = await this.taskRepo.find({
      where: { status: TaskStatus.PROCESSING },
    });

    for (const task of tasks) {
      const groups = await this.groupRepo.find({
        where: { taskId: task.id },
      });

      if (groups.length === 0) {
        // Check if task is created more than 30 minutes ago
        const createdAt = task.createdAt ? new Date(task.createdAt).getTime() : 0;
        if (createdAt && Date.now() - createdAt > 30 * 60 * 1000) {
          await this.taskRepo.update(task.id, { status: TaskStatus.COMPLETED });
          this.logger.log(`Task ${task.id} completed (empty groups timeout)`);
        }
        continue;
      }

      // 检查所有组是否都完成了
      const allGroupsFinished = groups.every((g) =>
        [TaskGroupStage.FINISHED, TaskGroupStage.FAILED].includes(g.stage),
      );

      if (allGroupsFinished) {
        const hasSuccess = groups.some((g) => g.stage === TaskGroupStage.FINISHED);
        const finalStatus = hasSuccess ? TaskStatus.COMPLETED : TaskStatus.FAILED;

        await this.taskRepo.update(task.id, { status: finalStatus });
        this.logger.log(
          `Task ${task.id} finished with status ${finalStatus} (${groups.length} groups)`
        );
      }
    }
  }
}
