import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { ConfigModule } from '@nestjs/config';
import { TaskService } from './task.service';
import { Task } from '@/src/entity/task.entity';
import { TaskGroup } from '@/src/entity/task-group.entity';
import { VideoArtifact } from '@/src/entity/video-artifact.entity';
import { AnalysisRecord } from '@/src/entity/analysis-record.entity';
import { User } from '@/src/entity/user.entity';
import { UserPointsRecord } from '@/src/entity/user-points-record.entity';
import { Prompt } from '@/src/entity/prompt.entity';
import { LarkModule } from '@/src/providers/lark/lark.module';
import { GroupVideoRunner } from './runner/video/group.video.runner';
import { DispatchVideoRunner } from './runner/video/dispatch.video.runner';
import { CreateSoraVideoRunner } from './runner/video/create.sora.video.runner';
import { PollingSoraVideoRunner } from './runner/video/polling.sora.video.runner';
import { TaskCompletionRunner } from './runner/video/task.completion.runner';
import { VideoProvider } from './provider/video.provider';
import { SorarpaWebApiService } from '@/src/module/common/api/sorarpa.api';
import { DayangyuWebApiService } from '@/src/module/common/api/dayangyu.web.api';
import { PoloWebApiService } from '@/src/module/common/api/polo.api';
import { SpiderModule } from '@/src/providers/spider/spider.module';
import { UserService } from '@/src/model/user.service';
import { AiModule } from '@/src/providers/ai/ai.module';
import { ThirdRecord } from '@/src/entity/third.record.entity';
import { ThirdRecordService } from '@/src/model/third.record.service';
import { AiGroupAgentService } from '@/src/module/common/agent/ai-group.agent.service';

@Module({
  imports: [
    TypeOrmModule.forFeature([Task, TaskGroup, VideoArtifact, AnalysisRecord, User, UserPointsRecord, Prompt, ThirdRecord]),
    ConfigModule,
    AiModule,
    LarkModule,
    SpiderModule,
  ],
  providers: [
    TaskService,
    SorarpaWebApiService, 
    DayangyuWebApiService,
    PoloWebApiService,
    UserService,
    ThirdRecordService,
    AiGroupAgentService,
    VideoProvider,

    // runner
    GroupVideoRunner,
    DispatchVideoRunner,
    CreateSoraVideoRunner,
    PollingSoraVideoRunner,
    TaskCompletionRunner,
  ],
  exports: [TaskService],
})
export class TaskModule {}
