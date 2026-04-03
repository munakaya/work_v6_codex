# OpenAPI YAML Reference

이 문서는 OpenAPI YAML 초안을 별도 레퍼런스로 분리한 파일이다. 구현 중 계약 검증이나 코드 생성 검토가 필요할 때만 집중해서 읽는다.


## 27. OpenAPI YAML 초안

아래는 초기 버전 Control Plane용 OpenAPI YAML 초안이다.
전체 엔드포인트를 모두 포함한 완성본은 아니고, MVP 구현에 필요한 핵심 경로와 스키마를 우선 정의한다.

```yaml
openapi: 3.1.0
info:
  title: Trading Platform Control Plane API
  version: 0.1.0
  description: >
    Automated trading platform control plane for bot registry,
    config management, strategy runs, order intents, orders, fills, and alerts.

servers:
  - url: https://api.example.com
    description: Production
  - url: https://staging-api.example.com
    description: Staging
  - url: http://localhost:8000
    description: Local

tags:
  - name: Health
  - name: Bots
  - name: Configs
  - name: StrategyRuns
  - name: OrderIntents
  - name: Orders
  - name: Alerts

paths:
  /api/v1/health:
    get:
      tags: [Health]
      summary: Health check
      operationId: getHealth
      responses:
        '200':
          description: Service is alive
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HealthResponse'

  /api/v1/ready:
    get:
      tags: [Health]
      summary: Readiness check
      operationId: getReadiness
      responses:
        '200':
          description: Service is ready
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReadyResponse'
        '503':
          description: Dependency unavailable

  /api/v1/bots/register:
    post:
      tags: [Bots]
      summary: Register a bot instance
      operationId: registerBot
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/BotRegisterRequest'
      responses:
        '200':
          description: Bot registered
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BotRegisterResponse'
        '409':
          description: Bot key already registered

  /api/v1/bots:
    get:
      tags: [Bots]
      summary: List bots
      operationId: listBots
      parameters:
        - in: query
          name: status
          schema:
            $ref: '#/components/schemas/StrategyStatus'
        - in: query
          name: strategy_name
          schema:
            type: string
        - in: query
          name: mode
          schema:
            $ref: '#/components/schemas/RunMode'
      responses:
        '200':
          description: Bot list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BotListResponse'

  /api/v1/bots/{bot_id}:
    get:
      tags: [Bots]
      summary: Get bot details
      operationId: getBot
      parameters:
        - $ref: '#/components/parameters/BotId'
      responses:
        '200':
          description: Bot detail
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BotDetailResponse'
        '404':
          description: Bot not found

  /api/v1/bots/{bot_id}/heartbeat:
    post:
      tags: [Bots]
      summary: Submit bot heartbeat
      operationId: submitHeartbeat
      parameters:
        - $ref: '#/components/parameters/BotId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/HeartbeatRequest'
      responses:
        '200':
          description: Heartbeat accepted
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HeartbeatResponse'
        '404':
          description: Bot not found

  /api/v1/configs:
    post:
      tags: [Configs]
      summary: Create config version
      operationId: createConfigVersion
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateConfigRequest'
      responses:
        '200':
          description: Config created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ConfigVersionResponse'

  /api/v1/configs/{config_scope}/latest:
    get:
      tags: [Configs]
      summary: Get latest config by scope
      operationId: getLatestConfig
      parameters:
        - in: path
          name: config_scope
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Latest config
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ConfigVersionResponse'
        '404':
          description: Config scope not found

  /api/v1/configs/{config_scope}/versions:
    get:
      tags: [Configs]
      summary: List config versions by scope
      operationId: listConfigVersions
      parameters:
        - in: path
          name: config_scope
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Config version list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ConfigVersionListResponse'
        '404':
          description: Config scope not found

  /api/v1/bots/{bot_id}/assign-config:
    post:
      tags: [Configs]
      summary: Assign config version to bot
      operationId: assignConfigToBot
      parameters:
        - $ref: '#/components/parameters/BotId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/AssignConfigRequest'
      responses:
        '202':
          description: Assignment accepted
        '404':
          description: Bot or config not found

  /api/v1/strategy-runs:
    post:
      tags: [StrategyRuns]
      summary: Create strategy run
      operationId: createStrategyRun
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateStrategyRunRequest'
      responses:
        '200':
          description: Strategy run created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StrategyRunResponse'
    get:
      tags: [StrategyRuns]
      summary: List strategy runs
      operationId: listStrategyRuns
      parameters:
        - in: query
          name: bot_id
          schema:
            type: string
            format: uuid
        - in: query
          name: status
          schema:
            $ref: '#/components/schemas/StrategyStatus'
      responses:
        '200':
          description: Strategy run list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StrategyRunListResponse'

  /api/v1/strategy-runs/{run_id}/start:
    post:
      tags: [StrategyRuns]
      summary: Start strategy run
      operationId: startStrategyRun
      parameters:
        - $ref: '#/components/parameters/RunId'
      responses:
        '202':
          description: Start accepted
        '404':
          description: Run not found

  /api/v1/strategy-runs/{run_id}/stop:
    post:
      tags: [StrategyRuns]
      summary: Stop strategy run
      operationId: stopStrategyRun
      parameters:
        - $ref: '#/components/parameters/RunId'
      responses:
        '202':
          description: Stop accepted
        '404':
          description: Run not found

  /api/v1/order-intents:
    get:
      tags: [OrderIntents]
      summary: List order intents
      operationId: listOrderIntents
      parameters:
        - in: query
          name: bot_id
          schema:
            type: string
            format: uuid
        - in: query
          name: strategy_run_id
          schema:
            type: string
            format: uuid
        - in: query
          name: market
          schema:
            type: string
        - in: query
          name: status
          schema:
            $ref: '#/components/schemas/OrderIntentStatus'
      responses:
        '200':
          description: Order intent list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OrderIntentListResponse'

  /api/v1/orders:
    get:
      tags: [Orders]
      summary: List orders
      operationId: listOrders
      parameters:
        - in: query
          name: bot_id
          schema:
            type: string
            format: uuid
        - in: query
          name: exchange_name
          schema:
            type: string
        - in: query
          name: status
          schema:
            $ref: '#/components/schemas/OrderStatus'
      responses:
        '200':
          description: Order list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OrderListResponse'

  /api/v1/alerts:
    get:
      tags: [Alerts]
      summary: List alerts
      operationId: listAlerts
      parameters:
        - in: query
          name: level
          schema:
            $ref: '#/components/schemas/AlertLevel'
        - in: query
          name: acknowledged
          schema:
            type: boolean
      responses:
        '200':
          description: Alert list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AlertListResponse'

  /api/v1/alerts/{alert_id}/ack:
    post:
      tags: [Alerts]
      summary: Acknowledge alert
      operationId: acknowledgeAlert
      parameters:
        - $ref: '#/components/parameters/AlertId'
      responses:
        '200':
          description: Alert acknowledged
        '404':
          description: Alert not found

  /api/v1/alerts/{alert_id}:
    get:
      tags: [Alerts]
      summary: Get alert detail
      operationId: getAlertDetail
      parameters:
        - $ref: '#/components/parameters/AlertId'
      responses:
        '200':
          description: Alert detail
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AlertEventResponse'
        '404':
          description: Alert not found

components:
  parameters:
    BotId:
      in: path
      name: bot_id
      required: true
      schema:
        type: string
        format: uuid
    RunId:
      in: path
      name: run_id
      required: true
      schema:
        type: string
        format: uuid
    AlertId:
      in: path
      name: alert_id
      required: true
      schema:
        type: string
        format: uuid

  schemas:
    RunMode:
      type: string
      enum: [dry_run, shadow, live]

    StrategyStatus:
      type: string
      enum: [pending, running, stopped, failed, completed]

    OrderIntentStatus:
      type: string
      enum: [created, submitted, cancelled, expired, rejected, simulated]

    OrderStatus:
      type: string
      enum: [new, partially_filled, filled, cancelled, rejected, expired]

    AlertLevel:
      type: string
      enum: [info, warn, error, critical]

    ApiError:
      type: object
      required: [code, message]
      properties:
        code:
          type: string
        message:
          type: string

    BotSummary:
      type: object
      required: [id, bot_key, strategy_name, mode, status]
      properties:
        id:
          type: string
          format: uuid
        bot_key:
          type: string
        strategy_name:
          type: string
        mode:
          $ref: '#/components/schemas/RunMode'
        status:
          $ref: '#/components/schemas/StrategyStatus'
        hostname:
          type: string
        last_seen_at:
          type: string
          format: date-time

    ConfigVersionSummary:
      type: object
      required: [id, config_scope, version_no, checksum, created_at]
      properties:
        id:
          type: string
          format: uuid
        config_scope:
          type: string
        version_no:
          type: integer
        checksum:
          type: string
        created_at:
          type: string
          format: date-time

    BotRegisterRequest:
      type: object
      required: [bot_key, strategy_name, mode]
      properties:
        bot_key:
          type: string
        strategy_name:
          type: string
        mode:
          $ref: '#/components/schemas/RunMode'
        hostname:
          type: string

    BotRegisterResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            bot:
              $ref: '#/components/schemas/BotSummary'
            assigned_config:
              $ref: '#/components/schemas/ConfigVersionSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    HeartbeatRequest:
      type: object
      required: [is_process_alive, is_market_data_alive, is_ordering_alive]
      properties:
        is_process_alive:
          type: boolean
        is_market_data_alive:
          type: boolean
        is_ordering_alive:
          type: boolean
        lag_ms:
          type: integer
        context:
          type: object
          additionalProperties: true

    HeartbeatResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            accepted:
              type: boolean
            server_time:
              type: string
              format: date-time
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    CreateConfigRequest:
      type: object
      required: [config_scope, config_json]
      properties:
        config_scope:
          type: string
        config_json:
          type: object
          additionalProperties: true

    AssignConfigRequest:
      type: object
      required: [config_version_id]
      properties:
        config_version_id:
          type: string
          format: uuid

    ConfigVersionResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          $ref: '#/components/schemas/ConfigVersionSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    CreateStrategyRunRequest:
      type: object
      required: [bot_id, strategy_name, mode]
      properties:
        bot_id:
          type: string
          format: uuid
        strategy_name:
          type: string
        mode:
          $ref: '#/components/schemas/RunMode'

    StrategyRunSummary:
      type: object
      properties:
        id:
          type: string
          format: uuid
        bot_id:
          type: string
          format: uuid
        strategy_name:
          type: string
        mode:
          $ref: '#/components/schemas/RunMode'
        status:
          $ref: '#/components/schemas/StrategyStatus'
        started_at:
          type: string
          format: date-time
        ended_at:
          type: string
          format: date-time

    StrategyRunResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          $ref: '#/components/schemas/StrategyRunSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    StrategyRunListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: array
          items:
            $ref: '#/components/schemas/StrategyRunSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    OrderIntentSummary:
      type: object
      properties:
        id:
          type: string
          format: uuid
        strategy_run_id:
          type: string
          format: uuid
        market:
          type: string
        buy_exchange:
          type: string
        sell_exchange:
          type: string
        target_qty:
          type: string
        expected_profit:
          type: string
        status:
          $ref: '#/components/schemas/OrderIntentStatus'
        created_at:
          type: string
          format: date-time

    OrderIntentListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: array
          items:
            $ref: '#/components/schemas/OrderIntentSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    OrderSummary:
      type: object
      properties:
        id:
          type: string
          format: uuid
        exchange_name:
          type: string
        market:
          type: string
        side:
          type: string
        quantity:
          type: string
        price:
          type: string
        status:
          $ref: '#/components/schemas/OrderStatus'

    OrderListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: array
          items:
            $ref: '#/components/schemas/OrderSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    AlertEventSummary:
      type: object
      properties:
        id:
          type: string
          format: uuid
        bot_id:
          type: string
          format: uuid
        level:
          $ref: '#/components/schemas/AlertLevel'
        code:
          type: string
        message:
          type: string
        created_at:
          type: string
          format: date-time
        acknowledged_at:
          type: string
          format: date-time
          nullable: true

    AlertListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: array
          items:
            $ref: '#/components/schemas/AlertEventSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    ConfigVersionListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            items:
              type: array
              items:
                $ref: '#/components/schemas/ConfigVersionSummary'
            count:
              type: integer
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    AlertEventResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          $ref: '#/components/schemas/AlertEventSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    HealthResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            status:
              type: string
            service:
              type: string
            version:
              type: string
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    ReadyResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            status:
              type: string
            database:
              type: string
            redis:
              type: string
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    BotListResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: array
          items:
            $ref: '#/components/schemas/BotSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    BotDetailResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            bot:
              $ref: '#/components/schemas/BotSummary'
            latest_config:
              $ref: '#/components/schemas/ConfigVersionSummary'
            latest_strategy_run:
              $ref: '#/components/schemas/StrategyRunSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'
```
