import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { TypeOrmForge } from '@/src/providers/forge/typeorm.forge';
import { Task } from '@/src/entity/task.entity';
import { TaskGroup } from '@/src/entity/task-group.entity';
import { VideoArtifact } from '@/src/entity/video-artifact.entity';
import { AnalysisRecord } from '@/src/entity/analysis-record.entity';
import { CloudModule } from '@/src/module/common/cloud/cloud.module';
import { AiModule } from '@/src/providers/ai/ai.module';
import { User } from '@/src/entity/user.entity';
import { UserPointsRecord } from '@/src/entity/user-points-record.entity';
import { Prompt } from '@/src/entity/prompt.entity';
import { CharacterRole } from '@/src/entity/character-role.entity';
import { UserAssetBinding } from '@/src/entity/user-asset-binding.entity';
import { UserService } from '@/src/model/user.service';
import { TaskModelService } from '@/src/module/api/services/task.service';
import { AnalysisService } from '@/src/module/api/services/analysis.service';
import { AnalysisAgentService } from '@/src/module/common/agent/analysis.agent.service';
import { PublicAuthController } from './controller/public/auth.controller';
import { TaskController } from './controller/public/task.controller';
import { AnalysisController } from './controller/public/analysis.controller';
import { CloudController } from './controller/public/cloud.controller';
import { UserController } from './controller/public/user.controller';
import { AttrsController } from './controller/public/attrs.controller';
import { CharacterLibraryController } from './controller/public/character-library.controller';
import { AuthService } from './services/auth.service';

@Module({
  imports: [
    TypeOrmModule.forFeature([Task, TaskGroup, VideoArtifact, AnalysisRecord, User, UserPointsRecord, Prompt, CharacterRole, UserAssetBinding]),
    CloudModule,
    AiModule,
  ],
  controllers: [PublicAuthController, TaskController, AnalysisController, CloudController, UserController, AttrsController, CharacterLibraryController],
  providers: [TypeOrmForge, UserService, AuthService, TaskModelService, AnalysisService, AnalysisAgentService],
})
export class PublicApiModule { }
