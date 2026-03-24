import { Injectable, Logger, Inject } from '@nestjs/common';
import { CronTaskService } from '../../providers/template/cron.task.service';
import { LarkService } from '../../providers/lark/ins.lark';
import { GroupVideoRunner } from './runner/video/group.video.runner';
import { DispatchVideoRunner } from './runner/video/dispatch.video.runner';
import { CreateSoraVideoRunner } from './runner/video/create.sora.video.runner';
import { PollingSoraVideoRunner } from './runner/video/polling.sora.video.runner';
import { TaskCompletionRunner } from './runner/video/task.completion.runner';

@Injectable()
export class TaskService extends CronTaskService {
  protected key = 'TaskService';
  protected logger: Logger;
  protected importantLogger: Logger;

  @Inject()
  protected larkIns: LarkService;

  @Inject()
  private readonly groupVideoRunner: GroupVideoRunner;

  @Inject()
  private readonly dispatchVideoRunner: DispatchVideoRunner;

  @Inject()
  private readonly createSoraVideoRunner: CreateSoraVideoRunner;

  @Inject()
  private readonly pollingSoraVideoRunner: PollingSoraVideoRunner;

  @Inject()
  private readonly taskCompletionRunner: TaskCompletionRunner;

  protected async initializeService(): Promise<void> {
    this.cycleConfig = {
      interval: 5000, // 5 seconds loop
      taskDuration: {},
      taskFirstRunDelay: {},
      taskFirstStartTime: {},
      startDurationRange: [100, 500],
      taskSleepTime: {},
    };

    this.logger = this.larkIns.msgIns().genLoggerWrapper(new Logger('TaskService'), 'TaskService',  this.config('lark').robots.baseRobot);
    this.importantLogger = this.larkIns.msgIns().genLoggerWrapper(new Logger('TaskServiceImportant'), 'TaskServiceImportant', this.config('lark').robots.importantRobot);

    // Register loggers for runners
    this.dispatchVideoRunner.register('logger', this.logger);
    this.createSoraVideoRunner.register('logger', this.logger);
    this.pollingSoraVideoRunner.register('logger', this.logger);
    this.taskCompletionRunner.register('logger', this.logger);
    // this.groupVideoRunner.register('logger', this.logger);
  }

  protected async registerTaskList(): Promise<void> {
    this.registerVideoRunners();
  }

  private registerVideoRunners() {
    // 0. Task Group Generation (Pending Task -> Task Groups)
    this.registerTask('TaskGroupGen', () => this.groupVideoRunner.run(), { interval: 15 * 1000, firstRunDelay: 1000  });

    // 1. Video Dispatch (Task Groups -> Artifacts)
    this.registerTask('VideoDispatch', () => this.dispatchVideoRunner.run(), { interval: 5 * 1000, firstRunDelay: 5000 });

    // 2. Video Creation (Created Artifact -> Generating)
    this.registerTask('VideoCreate', () => this.createSoraVideoRunner.run(), { interval: 15 * 1000, firstRunDelay: 10000 });

    // 3. Status Polling (Generating -> Completed)
    this.registerTask('VideoPolling', () => this.pollingSoraVideoRunner.run(), { interval: 20 * 1000, firstRunDelay: 15 * 1000 });

    // 5. Completion Check (Reviewing -> Finished -> Completed)
    this.registerTask('TaskCompletion', () => this.taskCompletionRunner.run(), { interval: 10000 });
  }
}
