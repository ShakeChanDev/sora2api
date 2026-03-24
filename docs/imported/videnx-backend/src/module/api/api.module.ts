import { Module, MiddlewareConsumer, NestModule, RequestMethod } from '@nestjs/common';
import { APP_FILTER, RouterModule } from '@nestjs/core';
import { PublicApiModule } from './public-api.module';
import { PublicAdminApiModule } from './public-admin-api.module';
import { ManagerModule } from './manager.module';
import { AdminJwtAuthMiddleware, PublicJwtAuthMiddleware } from '@/src/common/middleware/auth.middleware';
import { AuthService } from './services/auth.service';
import { ApiExceptionFilter } from '@/src/common/filter/api.exception.filter';

@Module({
  imports: [
    RouterModule.register([{ path: 'api', module: PublicApiModule }]),
    RouterModule.register([{ path: 'admin/api', module: PublicAdminApiModule }]),
    RouterModule.register([{ path: 'admin/manager', module: ManagerModule }]),
    PublicApiModule,
    PublicAdminApiModule,
    ManagerModule,
  ],
  providers: [
    AuthService,
    AdminJwtAuthMiddleware,
    PublicJwtAuthMiddleware,
    {
      provide: APP_FILTER,
      useClass: ApiExceptionFilter,
    },
  ],
})
export class ApiModule implements NestModule {
  configure(consumer: MiddlewareConsumer) {
    consumer
      .apply(PublicJwtAuthMiddleware)
      .exclude({ path: 'api/auth/login', method: RequestMethod.POST })
      .forRoutes({ path: 'api/*path', method: RequestMethod.ALL })

    consumer.apply(AdminJwtAuthMiddleware).forRoutes({ path: 'admin/api/*path', method: RequestMethod.ALL })

    consumer
      .apply(AdminJwtAuthMiddleware)
      .exclude({ path: 'admin/manager/auth/login', method: RequestMethod.POST })
      .forRoutes({ path: 'admin/manager/*path', method: RequestMethod.ALL })
  }
}
