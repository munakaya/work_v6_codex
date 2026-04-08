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
    When TP_ADMIN_TOKEN is configured, write endpoints require Bearer auth and
    may return 401 or 429.

servers:
  - url: https://api.example.com
    description: Production
  - url: https://staging-api.example.com
    description: Staging
  - url: http://localhost:38765
    description: Local

tags:
  - name: Health
  - name: MarketData
  - name: Recovery
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

  /api/v1/recovery-traces:
    get:
      tags: [Recovery]
      summary: List recovery traces
      operationId: listRecoveryTraces
      parameters:
        - in: query
          name: limit
          schema:
            type: integer
        - in: query
          name: bot_id
          schema:
            type: string
        - in: query
          name: run_id
          schema:
            type: string
        - in: query
          name: status
          schema:
            type: string
        - in: query
          name: lifecycle_state
          schema:
            type: string
      responses:
        '200':
          description: Recovery trace list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RecoveryTraceListResponse'
        '502':
          description: Redis runtime read failed
        '503':
          description: Redis runtime unavailable

  /api/v1/recovery-traces/{recovery_trace_id}:
    get:
      tags: [Recovery]
      summary: Get recovery trace
      operationId: getRecoveryTrace
      parameters:
        - in: path
          name: recovery_trace_id
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Recovery trace detail
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RecoveryTraceResponse'
        '404':
          description: Recovery trace not found
        '503':
          description: Redis runtime unavailable

  /api/v1/recovery-traces/{recovery_trace_id}/resolve:
    post:
      tags: [Recovery]
      summary: Resolve recovery trace
      operationId: resolveRecoveryTrace
      parameters:
        - in: path
          name: recovery_trace_id
          required: true
          schema:
            type: string
        - in: header
          name: X-Trace-Id
          required: false
          schema:
            type: string
      requestBody:
        required: false
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RecoveryTraceActionRequest'
      responses:
        '200':
          description: Recovery trace resolved
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RecoveryTraceResponse'
        '404':
          description: Recovery trace not found
        '409':
          description: Recovery trace already terminal or residual exposure remains
        '503':
          description: Redis runtime unavailable

  /api/v1/recovery-traces/{recovery_trace_id}/handoff:
    post:
      tags: [Recovery]
      summary: Mark recovery trace as manual handoff
      operationId: handoffRecoveryTrace
      parameters:
        - in: path
          name: recovery_trace_id
          required: true
          schema:
            type: string
        - in: header
          name: X-Trace-Id
          required: false
          schema:
            type: string
      requestBody:
        required: false
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RecoveryTraceActionRequest'
      responses:
        '200':
          description: Recovery trace marked as handoff required
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RecoveryTraceResponse'
        '404':
          description: Recovery trace not found
        '409':
          description: Recovery trace already terminal
        '503':
          description: Redis runtime unavailable

  /api/v1/recovery-traces/{recovery_trace_id}/start-unwind:
    post:
      tags: [Recovery]
      summary: Mark recovery trace as unwind in progress
      operationId: startUnwindRecoveryTrace
      parameters:
        - in: path
          name: recovery_trace_id
          required: true
          schema:
            type: string
        - in: header
          name: X-Trace-Id
          required: false
          schema:
            type: string
      requestBody:
        required: false
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RecoveryTraceActionRequest'
      responses:
        '200':
          description: Recovery trace marked as unwind in progress
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RecoveryTraceResponse'
        '404':
          description: Recovery trace not found
        '409':
          description: Recovery trace already terminal
        '503':
          description: Redis runtime unavailable

  /api/v1/recovery-traces/{recovery_trace_id}/submit-unwind-order:
    post:
      tags: [Recovery]
      summary: Create unwind order under linked recovery unwind intent
      operationId: submitRecoveryTraceUnwindOrder
      parameters:
        - in: path
          name: recovery_trace_id
          required: true
          schema:
            type: string
        - in: header
          name: X-Trace-Id
          required: false
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RecoveryTraceUnwindOrderRequest'
      responses:
        '201':
          description: Unwind order created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RecoveryTraceResponse'
        '400':
          description: Invalid request
        '404':
          description: Recovery trace or linked unwind intent not found
        '409':
          description: Recovery trace already terminal or linked unwind order already exists
        '422':
          description: Linked unwind intent validation failed
        '503':
          description: Redis runtime unavailable

  /api/v1/recovery-traces/{recovery_trace_id}/record-unwind-fill:
    post:
      tags: [Recovery]
      summary: Record unwind fill for linked recovery unwind order
      operationId: recordRecoveryTraceUnwindFill
      parameters:
        - in: path
          name: recovery_trace_id
          required: true
          schema:
            type: string
        - in: header
          name: X-Trace-Id
          required: false
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RecoveryTraceUnwindFillRequest'
      responses:
        '201':
          description: Unwind fill created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RecoveryTraceResponse'
        '400':
          description: Invalid request
        '404':
          description: Recovery trace or linked unwind order not found
        '409':
          description: Recovery trace already terminal or duplicate fill
        '422':
          description: Linked unwind order fill validation failed
        '503':
          description: Redis runtime unavailable

  /api/v1/recovery-traces/{recovery_trace_id}/record-reconciliation:
    post:
      tags: [Recovery]
      summary: Record reconciliation result for recovery trace
      operationId: recordRecoveryTraceReconciliation
      parameters:
        - in: path
          name: recovery_trace_id
          required: true
          schema:
            type: string
        - in: header
          name: X-Trace-Id
          required: false
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RecoveryTraceReconciliationRequest'
      responses:
        '200':
          description: Reconciliation result recorded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RecoveryTraceResponse'
        '400':
          description: Invalid request
        '404':
          description: Recovery trace not found
        '409':
          description: Recovery trace already terminal
        '503':
          description: Redis runtime unavailable

  /api/v1/market-data/orderbook-top:
    get:
      tags: [MarketData]
      summary: Get public orderbook top
      operationId: getOrderbookTop
      parameters:
        - in: query
          name: exchange
          required: true
          schema:
            type: string
        - in: query
          name: market
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Latest orderbook top snapshot
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MarketOrderbookTopResponse'
        '400':
          description: Invalid request
        '404':
          description: Market not found
        '502':
          description: Upstream provider error
        '503':
          description: Upstream rate limited

  /api/v1/market-data/orderbook-top/cached:
    get:
      tags: [MarketData]
      summary: Get cached public orderbook top
      operationId: getCachedOrderbookTop
      parameters:
        - in: query
          name: exchange
          required: true
          schema:
            type: string
        - in: query
          name: market
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Cached orderbook top snapshot
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MarketOrderbookTopResponse'
        '400':
          description: Invalid request
        '404':
          description: Cached snapshot not found
        '503':
          description: Redis runtime unavailable

  /api/v1/market-data/runtime:
    get:
      tags: [MarketData]
      summary: Get market data runtime status
      operationId: getMarketDataRuntime
      responses:
        '200':
          description: Runtime state and cached snapshots
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MarketDataRuntimeResponse'

  /api/v1/market-data/snapshots:
    get:
      tags: [MarketData]
      summary: List cached market snapshots
      operationId: listMarketSnapshots
      parameters:
        - in: query
          name: limit
          schema:
            type: integer
        - in: query
          name: exchange
          schema:
            type: string
        - in: query
          name: market
          schema:
            type: string
      responses:
        '200':
          description: Cached market snapshots
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MarketSnapshotListResponse'
        '502':
          description: Redis runtime read failed
        '503':
          description: Redis runtime unavailable

  /api/v1/market-data/poll:
    post:
      tags: [MarketData]
      summary: Refresh market snapshots now
      operationId: pollMarketSnapshots
      security:
        - AdminBearerAuth: []
      parameters:
        - in: header
          name: X-Trace-Id
          required: false
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/MarketDataPollRequest'
      responses:
        '200':
          description: Poll completed without upstream errors
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MarketDataPollResponse'
        '207':
          description: Poll completed with partial upstream errors
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MarketDataPollResponse'
        '400':
          description: Invalid request
        '401':
          $ref: '#/components/responses/UnauthorizedWrite'
        '429':
          $ref: '#/components/responses/WriteRateLimited'

  /api/v1/market-data/events:
    get:
      tags: [MarketData]
      summary: List cached market events
      operationId: listMarketEvents
      parameters:
        - in: query
          name: limit
          schema:
            type: integer
        - in: query
          name: before_stream_id
          schema:
            type: string
        - in: query
          name: exchange
          schema:
            type: string
        - in: query
          name: market
          schema:
            type: string
        - in: query
          name: event_type
          schema:
            type: string
        - in: query
          name: trace_id
          schema:
            type: string
      responses:
        '200':
          description: Recent market events
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MarketEventListResponse'
        '502':
          description: Redis stream read failed
        '503':
          description: Redis runtime unavailable

  /api/v1/runtime/streams:
    get:
      tags: [Runtime]
      summary: List Redis runtime stream summaries
      operationId: listRuntimeStreams
      parameters:
        - in: query
          name: stream_name
          schema:
            type: string
        - in: query
          name: limit
          schema:
            type: integer
            minimum: 1
            maximum: 5
        - in: query
          name: include_empty
          schema:
            type: boolean
        - in: query
          name: status
          schema:
            type: string
            enum: [empty, fresh, stale]
        - in: query
          name: stale_only
          schema:
            type: boolean
        - in: query
          name: sort_by
          schema:
            type: string
            enum: [stream_name, length, newest_age_seconds]
        - in: query
          name: order
          schema:
            type: string
        - in: query
          name: stale_after_seconds
          schema:
            type: integer
      responses:
        '200':
          description: Runtime stream summaries
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RuntimeStreamSummaryListResponse'
        '502':
          description: Redis runtime read failed
        '503':
          description: Redis runtime unavailable

  /api/v1/runtime/private-connectors:
    get:
      tags: [Runtime]
      summary: List private exchange connector states
      operationId: listPrivateExchangeConnectors
      parameters:
        - in: query
          name: exchange
          schema:
            type: string
            enum: [upbit, bithumb, coinone]
      responses:
        '200':
          description: Private exchange connector states
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/PrivateExchangeConnectorListResponse'
        '404':
          description: Requested private connector exchange not found

  /api/v1/runtime/private-ws:
    get:
      tags: [Runtime]
      summary: List private websocket monitor states
      operationId: listPrivateExchangeWebsocketStates
      parameters:
        - in: query
          name: exchange
          schema:
            type: string
            enum: [upbit, bithumb, coinone]
      responses:
        '200':
          description: Private websocket monitor states
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/PrivateExchangeWebsocketListResponse'
        '404':
          description: Requested private websocket exchange not found

  /api/v1/bots/events:
    get:
      tags: [Bots]
      summary: List bot runtime events
      operationId: listBotEvents
      parameters:
        - in: query
          name: limit
          schema:
            type: integer
        - in: query
          name: before_stream_id
          schema:
            type: string
        - in: query
          name: event_type
          schema:
            type: string
        - in: query
          name: trace_id
          schema:
            type: string
        - in: query
          name: bot_id
          schema:
            type: string
        - in: query
          name: bot_key
          schema:
            type: string
      responses:
        '200':
          description: Recent bot events
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RuntimeEventListResponse'
        '502':
          description: Redis stream read failed
        '503':
          description: Redis runtime unavailable

  /api/v1/bots/register:
    post:
      tags: [Bots]
      summary: Register a bot instance
      operationId: registerBot
      security:
        - AdminBearerAuth: []
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
        '401':
          $ref: '#/components/responses/UnauthorizedWrite'
        '429':
          $ref: '#/components/responses/WriteRateLimited'
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
      security:
        - AdminBearerAuth: []
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
        '401':
          $ref: '#/components/responses/UnauthorizedWrite'
        '429':
          $ref: '#/components/responses/WriteRateLimited'
        '404':
          description: Bot not found

  /api/v1/configs:
    post:
      tags: [Configs]
      summary: Create config version
      operationId: createConfigVersion
      security:
        - AdminBearerAuth: []
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
        '401':
          $ref: '#/components/responses/UnauthorizedWrite'
        '429':
          $ref: '#/components/responses/WriteRateLimited'

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

  /api/v1/strategy-runs/{run_id}/evaluate-arbitrage:
    post:
      tags: [StrategyRuns]
      summary: Evaluate arbitrage opportunity for a strategy run
      operationId: evaluateArbitrage
      parameters:
        - $ref: '#/components/parameters/RunId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/EvaluateArbitrageRequest'
      responses:
        '200':
          description: Evaluation completed without persistence
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/EvaluateArbitrageResponse'
        '201':
          description: Evaluation completed and order intent persisted
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/EvaluateArbitrageResponse'
        '400':
          description: Invalid request
        '404':
          description: Strategy run not found
        '409':
          description: Strategy execution disabled
        '422':
          description: Strategy not supported
        '501':
          description: Mutation unavailable for current backend

  /api/v1/strategy-runs/{run_id}/latest-evaluation:
    get:
      tags: [StrategyRuns]
      summary: Get latest cached arbitrage evaluation for a strategy run
      operationId: getLatestArbitrageEvaluation
      parameters:
        - $ref: '#/components/parameters/RunId'
      responses:
        '200':
          description: Latest cached evaluation
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/EvaluateArbitrageResponse'
        '404':
          description: Latest evaluation not found
        '503':
          description: Redis runtime unavailable

  /api/v1/strategy-runs/latest-evaluations:
    get:
      tags: [StrategyRuns]
      summary: List latest cached arbitrage evaluations
      operationId: listLatestArbitrageEvaluations
      parameters:
        - in: query
          name: limit
          schema:
            type: integer
        - in: query
          name: bot_id
          schema:
            type: string
        - in: query
          name: accepted
          schema:
            type: boolean
        - in: query
          name: lifecycle_preview
          schema:
            type: string
        - in: query
          name: reason_code
          schema:
            type: string
        - in: query
          name: stale_after_seconds
          schema:
            type: integer
            minimum: 0
        - in: query
          name: stale_only
          schema:
            type: boolean
      responses:
        '200':
          description: Latest cached evaluations by strategy run
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/EvaluateArbitrageListResponse'
        '400':
          description: Invalid request
        '502':
          description: Redis runtime read failed
        '503':
          description: Redis runtime unavailable

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

  /api/v1/strategy-runs/events:
    get:
      tags: [StrategyRuns]
      summary: List strategy runtime events
      operationId: listStrategyEvents
      parameters:
        - in: query
          name: limit
          schema:
            type: integer
        - in: query
          name: before_stream_id
          schema:
            type: string
        - in: query
          name: event_type
          schema:
            type: string
        - in: query
          name: trace_id
          schema:
            type: string
        - in: query
          name: bot_id
          schema:
            type: string
        - in: query
          name: run_id
          schema:
            type: string
        - in: query
          name: config_scope
          schema:
            type: string
      responses:
        '200':
          description: Recent strategy events
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RuntimeEventListResponse'
        '502':
          description: Redis stream read failed
        '503':
          description: Redis runtime unavailable

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
    post:
      tags: [OrderIntents]
      summary: Create order intent
      operationId: createOrderIntent
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateOrderIntentRequest'
      responses:
        '201':
          description: Order intent created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OrderIntentResponse'
        '400':
          description: Invalid request
        '404':
          description: Strategy run not found

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
    post:
      tags: [Orders]
      summary: Create order
      operationId: createOrder
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateOrderRequest'
      responses:
        '201':
          description: Order created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OrderResponse'
        '400':
          description: Invalid request
        '404':
          description: Order intent not found
        '409':
          description: Duplicate exchange order
        '422':
          description: Order validation failed

  /api/v1/orders/events:
    get:
      tags: [Orders]
      summary: List order runtime events
      operationId: listOrderEvents
      parameters:
        - in: query
          name: limit
          schema:
            type: integer
        - in: query
          name: before_stream_id
          schema:
            type: string
        - in: query
          name: event_type
          schema:
            type: string
        - in: query
          name: trace_id
          schema:
            type: string
        - in: query
          name: bot_id
          schema:
            type: string
        - in: query
          name: order_id
          schema:
            type: string
        - in: query
          name: order_intent_id
          schema:
            type: string
        - in: query
          name: exchange_name
          schema:
            type: string
        - in: query
          name: exchange
          schema:
            type: string
      responses:
        '200':
          description: Recent order events
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RuntimeEventListResponse'
        '502':
          description: Redis stream read failed
        '503':
          description: Redis runtime unavailable

  /api/v1/fills:
    get:
      tags: [Orders]
      summary: List fills
      operationId: listFills
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
          name: market
          schema:
            type: string
        - in: query
          name: strategy_run_id
          schema:
            type: string
            format: uuid
        - in: query
          name: order_id
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: Fill list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/FillListResponse'
    post:
      tags: [Orders]
      summary: Create fill
      operationId: createFill
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateFillRequest'
      responses:
        '201':
          description: Fill created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/FillResponse'
        '400':
          description: Invalid request
        '404':
          description: Order not found
        '409':
          description: Duplicate exchange trade
        '422':
          description: Fill validation failed

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

  /api/v1/alerts/events:
    get:
      tags: [Alerts]
      summary: List alert runtime events
      operationId: listAlertEvents
      parameters:
        - in: query
          name: limit
          schema:
            type: integer
        - in: query
          name: before_stream_id
          schema:
            type: string
        - in: query
          name: event_type
          schema:
            type: string
        - in: query
          name: trace_id
          schema:
            type: string
        - in: query
          name: bot_id
          schema:
            type: string
        - in: query
          name: alert_id
          schema:
            type: string
        - in: query
          name: level
          schema:
            type: string
      responses:
        '200':
          description: Recent alert events
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RuntimeEventListResponse'
        '502':
          description: Redis stream read failed
        '503':
          description: Redis runtime unavailable

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
  securitySchemes:
    AdminBearerAuth:
      type: http
      scheme: bearer
      bearerFormat: opaque

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

    EvaluateArbitrageRequest:
      type: object
      required:
        - canonical_symbol
        - market
        - base_exchange
        - hedge_exchange
        - base_orderbook
        - hedge_orderbook
        - base_balance
        - hedge_balance
        - risk_config
        - runtime_state
      properties:
        persist_intent:
          type: boolean
        execute:
          type: boolean
        canonical_symbol:
          type: string
        market:
          type: string
        base_exchange:
          type: string
        hedge_exchange:
          type: string
        base_orderbook:
          type: object
          additionalProperties: true
        hedge_orderbook:
          type: object
          additionalProperties: true
        base_balance:
          type: object
          additionalProperties: true
        hedge_balance:
          type: object
          additionalProperties: true
        risk_config:
          type: object
          additionalProperties: true
        runtime_state:
          type: object
          additionalProperties: true

    CreateOrderIntentRequest:
      type: object
      required: [strategy_run_id, market, buy_exchange, sell_exchange, side_pair, target_qty]
      properties:
        strategy_run_id:
          type: string
          format: uuid
        market:
          type: string
        buy_exchange:
          type: string
        sell_exchange:
          type: string
        side_pair:
          type: string
        target_qty:
          type: string
        expected_profit:
          type: string
        expected_profit_ratio:
          type: string
        status:
          $ref: '#/components/schemas/OrderIntentStatus'
        decision_context:
          $ref: '#/components/schemas/StrategyDecisionContext'

    CreateOrderRequest:
      type: object
      required: [order_intent_id, exchange_name, market, side, requested_qty]
      properties:
        order_intent_id:
          type: string
          format: uuid
        exchange_name:
          type: string
        exchange_order_id:
          type: string
        market:
          type: string
        side:
          type: string
          enum: [buy, sell]
        requested_price:
          type: string
        requested_qty:
          type: string
        status:
          $ref: '#/components/schemas/OrderStatus'
        raw_payload:
          type: object
          additionalProperties: true

    CreateFillRequest:
      type: object
      required: [order_id, fill_price, fill_qty, filled_at]
      properties:
        order_id:
          type: string
          format: uuid
        exchange_trade_id:
          type: string
        fill_price:
          type: string
        fill_qty:
          type: string
        fee_asset:
          type: string
        fee_amount:
          type: string
        filled_at:
          type: string
          format: date-time

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

    EvaluateArbitrageCandidateSize:
      type: object
      properties:
        target_qty:
          type: string
        components:
          type: object
          additionalProperties:
            type: string

    EvaluateArbitrageExecutableEdge:
      type: object
      properties:
        executable_buy_cost_quote:
          type: string
        executable_sell_proceeds_quote:
          type: string
        gross_profit_quote:
          type: string
        executable_profit_quote:
          type: string
        executable_profit_bps:
          type: string
        fee_buy_quote:
          type: string
        fee_sell_quote:
          type: string
        buy_slippage_buffer_quote:
          type: string
        sell_slippage_buffer_quote:
          type: string
        unwind_buffer_quote:
          type: string
        rebalance_buffer_quote:
          type: string
        total_fee_quote:
          type: string
        total_cost_adjustment_quote:
          type: string

    EvaluateArbitrageReservationPlan:
      type: object
      properties:
        reservation_passed:
          type: boolean
        reason_code:
          oneOf:
            - type: 'null'
            - type: string
        quote_required:
          type: string
        base_required:
          type: string
        reserved_notional:
          type: string
        details:
          type: object
          additionalProperties:
            type: string

    EvaluateArbitrageSubmitFailurePreview:
      type: object
      properties:
        without_auto_unwind:
          type: string
        with_auto_unwind:
          type: string

    EvaluateArbitrageResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            bot_id:
              type: string
            strategy_run_id:
              type: string
            accepted:
              type: boolean
            reason_code:
              type: string
            lifecycle_preview:
              type: string
            recovery_trace_id:
              oneOf:
                - type: 'null'
                - type: string
            recovery_status:
              oneOf:
                - type: 'null'
                - type: string
            recovery_lifecycle_state:
              oneOf:
                - type: 'null'
                - type: string
            recovery_updated_at:
              oneOf:
                - type: 'null'
                - type: string
                  format: date-time
            cached_at:
              type: string
              format: date-time
            decision_context:
              $ref: '#/components/schemas/StrategyDecisionContext'
            candidate_size:
              oneOf:
                - type: 'null'
                - $ref: '#/components/schemas/EvaluateArbitrageCandidateSize'
            executable_edge:
              oneOf:
                - type: 'null'
                - $ref: '#/components/schemas/EvaluateArbitrageExecutableEdge'
            reservation_plan:
              oneOf:
                - type: 'null'
                - $ref: '#/components/schemas/EvaluateArbitrageReservationPlan'
            submit_failure_preview:
              oneOf:
                - type: 'null'
                - $ref: '#/components/schemas/EvaluateArbitrageSubmitFailurePreview'
            persisted_intent:
              oneOf:
                - type: 'null'
                - $ref: '#/components/schemas/OrderIntentDetail'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    EvaluateArbitrageListResponse:
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
                type: object
                properties:
                  bot_id:
                    type: string
                  strategy_run_id:
                    type: string
                  accepted:
                    type: boolean
                  reason_code:
                    type: string
                  lifecycle_preview:
                    type: string
                  recovery_trace_id:
                    oneOf:
                      - type: 'null'
                      - type: string
                  recovery_status:
                    oneOf:
                      - type: 'null'
                      - type: string
                  recovery_lifecycle_state:
                    oneOf:
                      - type: 'null'
                      - type: string
                  recovery_updated_at:
                    oneOf:
                      - type: 'null'
                      - type: string
                        format: date-time
                  cached_at:
                    type: string
                    format: date-time
                  cached_age_seconds:
                    oneOf:
                      - type: 'null'
                      - type: integer
                  is_stale:
                    oneOf:
                      - type: 'null'
                      - type: boolean
                  decision_context:
                    $ref: '#/components/schemas/StrategyDecisionContext'
                  candidate_size:
                    oneOf:
                      - type: 'null'
                      - $ref: '#/components/schemas/EvaluateArbitrageCandidateSize'
                  executable_edge:
                    oneOf:
                      - type: 'null'
                      - $ref: '#/components/schemas/EvaluateArbitrageExecutableEdge'
                  reservation_plan:
                    oneOf:
                      - type: 'null'
                      - $ref: '#/components/schemas/EvaluateArbitrageReservationPlan'
                  submit_failure_preview:
                    oneOf:
                      - type: 'null'
                      - $ref: '#/components/schemas/EvaluateArbitrageSubmitFailurePreview'
                  persisted_intent:
                    oneOf:
                      - type: 'null'
                      - $ref: '#/components/schemas/OrderIntentDetail'
            count:
              type: integer
            matched_count:
              type: integer
            accepted_count:
              type: integer
            rejected_count:
              type: integer
            unique_bot_count:
              type: integer
            newest_cached_at:
              oneOf:
                - type: 'null'
                - type: string
                  format: date-time
            oldest_cached_at:
              oneOf:
                - type: 'null'
                - type: string
                  format: date-time
            stale_after_seconds:
              oneOf:
                - type: 'null'
                - type: integer
            stale_count:
              oneOf:
                - type: 'null'
                - type: integer
            reason_code_counts:
              type: object
              additionalProperties:
                type: integer
            lifecycle_preview_counts:
              type: object
              additionalProperties:
                type: integer
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

    OrderIntentDetail:
      type: object
      properties:
        intent_id:
          type: string
          format: uuid
        bot_id:
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
        side_pair:
          type: string
        target_qty:
          type: string
        expected_profit:
          type: string
          nullable: true
        expected_profit_ratio:
          type: string
          nullable: true
        status:
          $ref: '#/components/schemas/OrderIntentStatus'
        created_at:
          type: string
          format: date-time
        decision_context:
          $ref: '#/components/schemas/StrategyDecisionContext'

    StrategyDecisionContext:
      type: object
      properties:
        decision_id:
          type: string
        quote_pair_id:
          type: string
        clock_skew_ms:
          type: integer
        gate_checks:
          type: array
          items:
            type: object
            properties:
              name:
                type: string
              passed:
                type: boolean
              detail:
                type: string
        computed:
          type: object
          properties:
            target_qty:
              oneOf:
                - type: 'null'
                - type: string
            depth_passed:
              oneOf:
                - type: 'null'
                - type: boolean
            buy_depth_levels:
              oneOf:
                - type: 'null'
                - type: string
            sell_depth_levels:
              oneOf:
                - type: 'null'
                - type: string
            buy_depth_notional_quote:
              oneOf:
                - type: 'null'
                - type: string
            sell_depth_notional_quote:
              oneOf:
                - type: 'null'
                - type: string
            executable_buy_cost_quote:
              oneOf:
                - type: 'null'
                - type: string
            executable_sell_proceeds_quote:
              oneOf:
                - type: 'null'
                - type: string
            gross_profit_quote:
              oneOf:
                - type: 'null'
                - type: string
            executable_profit_quote:
              oneOf:
                - type: 'null'
                - type: string
            executable_profit_bps:
              oneOf:
                - type: 'null'
                - type: string
            fee_buy_quote:
              oneOf:
                - type: 'null'
                - type: string
            fee_sell_quote:
              oneOf:
                - type: 'null'
                - type: string
            buy_slippage_buffer_quote:
              oneOf:
                - type: 'null'
                - type: string
            sell_slippage_buffer_quote:
              oneOf:
                - type: 'null'
                - type: string
            unwind_buffer_quote:
              oneOf:
                - type: 'null'
                - type: string
            rebalance_buffer_quote:
              oneOf:
                - type: 'null'
                - type: string
            total_cost_adjustment_quote:
              oneOf:
                - type: 'null'
                - type: string
        reservation:
          type: object
          properties:
            reservation_passed:
              type: boolean
            quote_required:
              oneOf:
                - type: 'null'
                - type: string
            base_required:
              oneOf:
                - type: 'null'
                - type: string
            details:
              type: object
              additionalProperties:
                type: string
        reservation_passed:
          type: boolean
        reason_code:
          type: string

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

    OrderIntentResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          $ref: '#/components/schemas/OrderIntentDetail'
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

    OrderDetail:
      type: object
      properties:
        order_id:
          type: string
          format: uuid
        order_intent_id:
          type: string
          format: uuid
        bot_id:
          type: string
          format: uuid
        strategy_run_id:
          type: string
          format: uuid
        exchange_name:
          type: string
        exchange_order_id:
          type: string
          nullable: true
        market:
          type: string
        side:
          type: string
          enum: [buy, sell]
        requested_price:
          type: string
          nullable: true
        requested_qty:
          type: string
        filled_qty:
          type: string
        avg_fill_price:
          type: string
          nullable: true
        fee_amount:
          type: string
          nullable: true
        status:
          $ref: '#/components/schemas/OrderStatus'
        internal_error_code:
          type: string
          nullable: true
        created_at:
          type: string
          format: date-time
        submitted_at:
          type: string
          format: date-time
          nullable: true
        updated_at:
          type: string
          format: date-time
        order_intent:
          $ref: '#/components/schemas/OrderIntentDetail'
        fills:
          type: array
          items:
            $ref: '#/components/schemas/FillSummary'
        reconciliation_events:
          type: array
          items:
            type: object
            additionalProperties: true
        decision_record:
          oneOf:
            - type: 'null'
            - type: object
              additionalProperties: true

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

    OrderResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          $ref: '#/components/schemas/OrderDetail'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    FillSummary:
      type: object
      properties:
        fill_id:
          type: string
          format: uuid
        order_id:
          type: string
          format: uuid
        order_intent_id:
          type: string
          format: uuid
          nullable: true
        bot_id:
          type: string
          format: uuid
          nullable: true
        strategy_run_id:
          type: string
          format: uuid
          nullable: true
        exchange_name:
          type: string
        exchange_trade_id:
          type: string
          nullable: true
        market:
          type: string
        side:
          type: string
          enum: [buy, sell]
        fill_price:
          type: string
        fill_qty:
          type: string
        fee_asset:
          type: string
          nullable: true
        fee_amount:
          type: string
          nullable: true
        order_status:
          $ref: '#/components/schemas/OrderStatus'
        filled_at:
          type: string
          format: date-time
        created_at:
          type: string
          format: date-time

    FillListResponse:
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
                $ref: '#/components/schemas/FillSummary'
            count:
              type: integer
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    FillResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          $ref: '#/components/schemas/FillSummary'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    MarketDataRateLimitItem:
      type: object
      properties:
        name:
          type: string
        rate_per_sec:
          type: number
        burst:
          type: integer
        enabled:
          type: boolean

    MarketDataRateLimitSummary:
      type: object
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/MarketDataRateLimitItem'
        count:
          type: integer
        retry_count:
          type: integer
        retry_backoff:
          type: object
          properties:
            initial_delay_ms:
              type: integer
            max_delay_ms:
              type: integer

    MarketDataRuntimeResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            runtime:
              type: object
              properties:
                enabled:
                  type: boolean
                exchange:
                  type: string
                markets:
                  type: array
                  items:
                    type: string
                interval_ms:
                  type: integer
                running:
                  type: boolean
                state:
                  type: string
                last_success_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_error_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_error_message:
                  oneOf:
                    - type: 'null'
                    - type: string
                success_count:
                  type: integer
                failure_count:
                  type: integer
            redis_runtime:
              type: object
              properties:
                configured:
                  type: boolean
                cli_available:
                  type: boolean
                enabled:
                  type: boolean
                key_prefix:
                  type: string
                state:
                  type: string
            rate_limits:
              $ref: '#/components/schemas/MarketDataRateLimitSummary'
            snapshots:
              type: array
              items:
                $ref: '#/components/schemas/MarketOrderbookTop'
            snapshot_count:
              type: integer
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
            service:
              type: string
            redis_key_prefix:
              type: string
            redis_runtime:
              type: object
              properties:
                configured:
                  type: boolean
                cli_available:
                  type: boolean
                enabled:
                  type: boolean
                key_prefix:
                  type: string
                state:
                  type: string
            market_data_runtime:
              type: object
              properties:
                enabled:
                  type: boolean
                exchange:
                  type: string
                markets:
                  type: array
                  items:
                    type: string
                interval_ms:
                  type: integer
                running:
                  type: boolean
                state:
                  type: string
                last_success_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_error_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_error_message:
                  oneOf:
                    - type: 'null'
                    - type: string
                success_count:
                  type: integer
                failure_count:
                  type: integer
            strategy_runtime:
              type: object
              properties:
                enabled:
                  type: boolean
                interval_ms:
                  type: integer
                persist_intent:
                  type: boolean
                execution_enabled:
                  type: boolean
                execution_mode:
                  type: string
                execution_adapter:
                  type: string
                auto_unwind_on_failure:
                  type: boolean
                running:
                  type: boolean
                state:
                  type: string
                last_success_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_error_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_error_message:
                  oneOf:
                    - type: 'null'
                    - type: string
                last_skip_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_skip_reason:
                  oneOf:
                    - type: 'null'
                    - type: string
                evaluated_count:
                  type: integer
                accepted_count:
                  type: integer
                rejected_count:
                  type: integer
                persisted_intent_count:
                  type: integer
                submit_attempt_count:
                  type: integer
                submit_success_count:
                  type: integer
                submit_failure_count:
                  type: integer
                skipped_count:
                  type: integer
                failure_count:
                  type: integer
            recovery_runtime:
              type: object
              properties:
                enabled:
                  type: boolean
                interval_ms:
                  type: integer
                handoff_after_seconds:
                  type: integer
                submit_timeout_seconds:
                  type: integer
                running:
                  type: boolean
                state:
                  type: string
                last_success_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_error_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_error_message:
                  oneOf:
                    - type: 'null'
                    - type: string
                last_resolution_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_handoff_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                processed_count:
                  type: integer
                resolved_count:
                  type: integer
                handoff_count:
                  type: integer
                skipped_count:
                  type: integer
                failure_count:
                  type: integer
            read_store:
              type: object
              properties:
                backend_name:
                  type: string
                supports_mutation:
                  type: boolean
                mode:
                  type: string
                driver_name:
                  oneOf:
                    - type: 'null'
                    - type: string
                driver_available:
                  type: boolean
                reason:
                  oneOf:
                    - type: 'null'
                    - type: string
            write_api_guard:
              type: object
              properties:
                auth_enabled:
                  type: boolean
                rate_limit_enabled:
                  type: boolean
                rate_limit_window_ms:
                  type: integer
                rate_limit_max_requests:
                  type: integer
            dependencies:
              type: object
              properties:
                postgres:
                  type: object
                  properties:
                    configured:
                      type: boolean
                    reachable:
                      type: boolean
                    state:
                      type: string
                    host:
                      oneOf:
                        - type: 'null'
                        - type: string
                    port:
                      oneOf:
                        - type: 'null'
                        - type: integer
                redis:
                  type: object
                  properties:
                    configured:
                      type: boolean
                    reachable:
                      type: boolean
                    state:
                      type: string
                    host:
                      oneOf:
                        - type: 'null'
                        - type: string
                    port:
                      oneOf:
                        - type: 'null'
                        - type: integer
                private_execution:
                  type: object
                  properties:
                    configured:
                      type: boolean
                    reachable:
                      type: boolean
                    state:
                      type: string
                    host:
                      oneOf:
                        - type: 'null'
                        - type: string
                    port:
                      oneOf:
                        - type: 'null'
                        - type: integer
                exchange_trading_keys:
                  type: object
                  properties:
                    count:
                      type: integer
                    configured_count:
                      type: integer
                    ready_count:
                      type: integer
                    overall_state:
                      type: string
                    items:
                      type: array
                      items:
                        $ref: '#/components/schemas/PrivateExchangeConnectorDependencyItem'
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    PrivateExchangeConnectorDependencyItem:
      type: object
      properties:
        exchange:
          type: string
        configured:
          type: boolean
        ready:
          type: boolean
        state:
          type: string
        source_path:
          oneOf:
            - type: 'null'
            - type: string
        primary_path:
          type: string
        fallback_path:
          type: string
        access_key_field:
          oneOf:
            - type: 'null'
            - type: string

    PrivateExchangeConnectorItem:
      type: object
      properties:
        exchange:
          type: string
        name:
          type: string
        configured:
          type: boolean
        ready:
          type: boolean
        state:
          type: string
        credential_source_path:
          oneOf:
            - type: 'null'
            - type: string

    PrivateExchangeConnectorListResponse:
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
                $ref: '#/components/schemas/PrivateExchangeConnectorItem'
            count:
              type: integer
            configured_count:
              type: integer
            ready_count:
              type: integer
            overall_state:
              type: string
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    PrivateExchangeWebsocketItem:
      type: object
      properties:
        exchange:
          type: string
        configured:
          type: boolean
        auth_ready:
          type: boolean
        connection_state:
          type: string
        disconnect_count:
          type: integer
        last_connected_at:
          oneOf:
            - type: 'null'
            - type: string
              format: date-time
        last_failed_at:
          oneOf:
            - type: 'null'
            - type: string
              format: date-time
        last_close_code:
          oneOf:
            - type: 'null'
            - type: integer
        last_close_category:
          oneOf:
            - type: 'null'
            - type: string
        endpoint:
          oneOf:
            - type: 'null'
            - type: string
        ping_interval_seconds:
          oneOf:
            - type: 'null'
            - type: integer
        idle_timeout_seconds:
          oneOf:
            - type: 'null'
            - type: integer
        connection_limit:
          oneOf:
            - type: 'null'
            - type: integer

    PrivateExchangeWebsocketListResponse:
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
                $ref: '#/components/schemas/PrivateExchangeWebsocketItem'
            count:
              type: integer
            configured_count:
              type: integer
            auth_ready_count:
              type: integer
            connected_count:
              type: integer
            overall_state:
              type: string
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    RecoveryTraceSummary:
      type: object
      properties:
        recovery_trace_id:
          type: string
        run_id:
          type: string
        bot_id:
          type: string
        intent_id:
          oneOf:
            - type: 'null'
            - type: string
        status:
          type: string
        lifecycle_state:
          type: string
        incident_code:
          oneOf:
            - type: 'null'
            - type: string
        reason_code:
          oneOf:
            - type: 'null'
            - type: string
        manual_handoff_required:
          type: boolean
        linked_unwind_action_id:
          oneOf:
            - type: 'null'
            - type: string
        linked_unwind_order_id:
          oneOf:
            - type: 'null'
            - type: string
        residual_exposure_quote:
          oneOf:
            - type: 'null'
            - type: string
        created_at:
          oneOf:
            - type: 'null'
            - type: string
              format: date-time
        updated_at:
          oneOf:
            - type: 'null'
            - type: string
              format: date-time
        closed_at:
          oneOf:
            - type: 'null'
            - type: string
              format: date-time
        resolution_reason:
          oneOf:
            - type: 'null'
            - type: string
        reconciliation_result:
          oneOf:
            - type: 'null'
            - type: string
        reconciliation_open_order_count:
          oneOf:
            - type: 'null'
            - type: integer
        reconciliation_residual_exposure_quote:
          oneOf:
            - type: 'null'
            - type: string
        reconciliation_observed_at:
          oneOf:
            - type: 'null'
            - type: string
              format: date-time
        reconciliation_observed_order_ids:
          oneOf:
            - type: 'null'
            - type: array
              items:
                type: string
        reconciliation_observed_fill_ids:
          oneOf:
            - type: 'null'
            - type: array
              items:
                type: string
        reconciliation_observed_order_statuses:
          oneOf:
            - type: 'null'
            - type: array
              items:
                type: object
                properties:
                  order_id:
                    type: string
                  status:
                    type: string
        reconciliation_observed_balances:
          oneOf:
            - type: 'null'
            - type: array
              items:
                type: object
                properties:
                  exchange_name:
                    type: string
                  asset:
                    type: string
                  free:
                    type: string
                  locked:
                    type: string
        reconciliation_attempt_count:
          oneOf:
            - type: 'null'
            - type: integer
        reconciliation_matched_count:
          oneOf:
            - type: 'null'
            - type: integer
        reconciliation_mismatch_count:
          oneOf:
            - type: 'null'
            - type: integer
        reconciliation_mismatch_streak:
          oneOf:
            - type: 'null'
            - type: integer
        reconciliation_reason:
          oneOf:
            - type: 'null'
            - type: string
        reconciliation_source:
          oneOf:
            - type: 'null'
            - type: string
        reconciliation_verified_by:
          oneOf:
            - type: 'null'
            - type: string
        reconciliation_updated_at:
          oneOf:
            - type: 'null'
            - type: string
              format: date-time
        handoff_reason:
          oneOf:
            - type: 'null'
            - type: string
        verified_by:
          oneOf:
            - type: 'null'
            - type: string
        summary:
          oneOf:
            - type: 'null'
            - type: string

    RecoveryTraceResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          allOf:
            - $ref: '#/components/schemas/RecoveryTraceSummary'
          properties:
            created_unwind_intent:
              oneOf:
                - type: 'null'
                - $ref: '#/components/schemas/OrderIntentDetail'
            created_unwind_order:
              oneOf:
                - type: 'null'
                - $ref: '#/components/schemas/OrderDetail'
            created_unwind_fill:
              oneOf:
                - type: 'null'
                - $ref: '#/components/schemas/FillSummary'
            latest_evaluation:
              oneOf:
                - type: 'null'
                - type: object
                  additionalProperties: true
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    RecoveryTraceListResponse:
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
                $ref: '#/components/schemas/RecoveryTraceSummary'
            count:
              type: integer
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    RecoveryTraceActionRequest:
      type: object
      properties:
        resolution_reason:
          type: string
        create_unwind_intent:
          type: boolean
        residual_exposure_quote:
          type: string
        market:
          type: string
        buy_exchange:
          type: string
        sell_exchange:
          type: string
        side_pair:
          type: string
        target_qty:
          type: string
        handoff_reason:
          type: string
        verified_by:
          type: string
        summary:
          type: string
        operator_context:
          type: object

    RecoveryTraceUnwindOrderRequest:
      type: object
      properties:
        exchange_name:
          type: string
        exchange_order_id:
          type: string
        market:
          type: string
        side:
          type: string
        requested_price:
          type: string
        requested_qty:
          type: string
        status:
          type: string
        raw_payload:
          type: object

    RecoveryTraceUnwindFillRequest:
      type: object
      properties:
        exchange_trade_id:
          type: string
        fill_price:
          type: string
        fill_qty:
          type: string
        fee_asset:
          type: string
        fee_amount:
          type: string
        filled_at:
          type: string
          format: date-time

    RecoveryTraceReconciliationRequest:
      type: object
      properties:
        matched:
          type: boolean
        open_order_count:
          type: integer
        residual_exposure_quote:
          type: string
        observed_at:
          type: string
          format: date-time
        observed_order_ids:
          type: array
          uniqueItems: true
          items:
            type: string
        observed_fill_ids:
          type: array
          uniqueItems: true
          items:
            type: string
        observed_order_statuses:
          type: array
          items:
            type: object
            properties:
              order_id:
                type: string
              status:
                type: string
        observed_balances:
          type: array
          items:
            type: object
            properties:
              exchange_name:
                type: string
              asset:
                type: string
              free:
                type: string
              locked:
                type: string
        reconciliation_reason:
          type: string
        summary:
          type: string
        source:
          type: string
        verified_by:
          type: string
        operator_context:
          type: object

    MarketOrderbookTopResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            exchange:
              type: string
            market:
              type: string
            best_bid:
              type: string
            best_ask:
              type: string
            bid_volume:
              type: string
            ask_volume:
              type: string
            exchange_timestamp:
              type: string
              format: date-time
            received_at:
              type: string
              format: date-time
            exchange_age_ms:
              type: integer
            stale:
              type: boolean
            source_type:
              type: string
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    MarketDataRuntimeResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            runtime:
              type: object
              properties:
                enabled:
                  type: boolean
                exchange:
                  type: string
                markets:
                  type: array
                  items:
                    type: string
                interval_ms:
                  type: integer
                running:
                  type: boolean
                state:
                  type: string
                last_success_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_error_at:
                  oneOf:
                    - type: 'null'
                    - type: string
                      format: date-time
                last_error_message:
                  oneOf:
                    - type: 'null'
                    - type: string
                success_count:
                  type: integer
                failure_count:
                  type: integer
            redis_runtime:
              type: object
              properties:
                configured:
                  type: boolean
                cli_available:
                  type: boolean
                enabled:
                  type: boolean
                key_prefix:
                  type: string
                state:
                  type: string
            snapshots:
              type: array
              items:
                type: object
                properties:
                  exchange:
                    type: string
                  market:
                    type: string
                  best_bid:
                    type: string
                  best_ask:
                    type: string
                  bid_volume:
                    type: string
                  ask_volume:
                    type: string
                  exchange_timestamp:
                    type: string
                    format: date-time
                  received_at:
                    type: string
                    format: date-time
                  exchange_age_ms:
                    type: integer
                  stale:
                    type: boolean
                  source_type:
                    type: string
            snapshot_count:
              type: integer
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    MarketSnapshotListResponse:
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
                type: object
                properties:
                  exchange:
                    type: string
                  market:
                    type: string
                  best_bid:
                    type: string
                  best_ask:
                    type: string
                  bid_volume:
                    type: string
                  ask_volume:
                    type: string
                  exchange_timestamp:
                    type: string
                    format: date-time
                  received_at:
                    type: string
                    format: date-time
                  exchange_age_ms:
                    type: integer
                  stale:
                    type: boolean
                  source_type:
                    type: string
            count:
              type: integer
            has_more:
              type: boolean
            next_before_stream_id:
              oneOf:
                - type: 'null'
                - type: string
            newest_stream_id:
              oneOf:
                - type: 'null'
                - type: string
            oldest_stream_id:
              oneOf:
                - type: 'null'
                - type: string
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    MarketDataPollRequest:
      type: object
      required: [exchange, markets]
      properties:
        exchange:
          type: string
        markets:
          type: array
          items:
            type: string

    MarketDataPollResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          properties:
            exchange:
              type: string
            requested_markets:
              type: array
              items:
                type: string
            items:
              type: array
              items:
                type: object
                properties:
                  exchange:
                    type: string
                  market:
                    type: string
                  best_bid:
                    type: string
                  best_ask:
                    type: string
                  bid_volume:
                    type: string
                  ask_volume:
                    type: string
                  exchange_timestamp:
                    type: string
                    format: date-time
                  received_at:
                    type: string
                    format: date-time
                  exchange_age_ms:
                    type: integer
                  stale:
                    type: boolean
                  source_type:
                    type: string
            count:
              type: integer
            errors:
              type: array
              items:
                type: object
                properties:
                  market:
                    type: string
                  code:
                    type: string
                  message:
                    type: string
                  status:
                    type: integer
            error_count:
              type: integer
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    MarketEventListResponse:
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
                type: object
                properties:
                  stream_id:
                    type: string
                  event_id:
                    type: string
                  event_type:
                    type: string
                  event_version:
                    type: integer
                  occurred_at:
                    type: string
                    format: date-time
                  producer:
                    type: string
                  trace_id:
                    oneOf:
                      - type: 'null'
                      - type: string
                  payload:
                    type: object
                    properties:
                      exchange:
                        type: string
                      market:
                        type: string
                      stale:
                        type: boolean
                      source_type:
                        type: string
                      exchange_age_ms:
                        type: integer
            count:
              type: integer
            has_more:
              type: boolean
            next_before_stream_id:
              oneOf:
                - type: 'null'
                - type: string
            newest_stream_id:
              oneOf:
                - type: 'null'
                - type: string
            oldest_stream_id:
              oneOf:
                - type: 'null'
                - type: string
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    RuntimeEventListResponse:
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
                type: object
                properties:
                  stream_id:
                    type: string
                  event_id:
                    type: string
                  event_type:
                    type: string
                  event_version:
                    type: integer
                  occurred_at:
                    type: string
                    format: date-time
                  producer:
                    type: string
                  trace_id:
                    oneOf:
                      - type: 'null'
                      - type: string
                  payload:
                    type: object
                    additionalProperties: true
            count:
              type: integer
        error:
          oneOf:
            - type: 'null'
            - $ref: '#/components/schemas/ApiError'

    RuntimeStreamSummaryListResponse:
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
                type: object
                properties:
                  stream_name:
                    type: string
                  length:
                    type: integer
                  newest_age_seconds:
                    oneOf:
                      - type: 'null'
                      - type: integer
                  is_stale:
                    oneOf:
                      - type: 'null'
                      - type: boolean
                  status:
                    type: string
                    enum: [empty, fresh, stale]
                  newest_stream_id:
                    oneOf:
                      - type: 'null'
                      - type: string
                  newest_occurred_at:
                    oneOf:
                      - type: 'null'
                      - type: string
                  oldest_stream_id:
                    oneOf:
                      - type: 'null'
                      - type: string
                  oldest_occurred_at:
                    oneOf:
                      - type: 'null'
                      - type: string
            count:
              type: integer
            matched_count:
              type: integer
            non_empty_count:
              type: integer
            total_length:
              type: integer
            stale_after_seconds:
              type: integer
            stale_count:
              type: integer
            stale_only:
              type: boolean
            status:
              oneOf:
                - type: 'null'
                - type: string
            status_counts:
              type: object
              properties:
                empty:
                  type: integer
                fresh:
                  type: integer
                stale:
                  type: integer
            overall_status:
              type: string
              enum: [empty, fresh, stale]
            limit:
              oneOf:
                - type: 'null'
                - type: integer
            has_more:
              type: boolean
            sort_by:
              type: string
            order:
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

  responses:
    UnauthorizedWrite:
      description: Missing or invalid bearer token for write API
    WriteRateLimited:
      description: Too many write requests from the same client IP
```
