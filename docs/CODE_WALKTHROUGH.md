# EchoAgent 代码解读

> 配合 [开发文档](DEVELOPMENT_PLAN.md) 一起看：开发文档讲"为什么这样设计"，这份文档讲"代码具体怎么实现的"。
> 建议打开编辑器，按第 2 节的阅读顺序，一边看代码一边看这里的解读。
> 文中的 `文件:行号` 指向写这份文档时的代码位置，之后改了代码，行号可能会有偏移。

---

## 目录

1. [先把项目跑起来](#1-先把项目跑起来)
2. [推荐的阅读顺序](#2-推荐的阅读顺序)
3. [一个请求的完整旅程](#3-一个请求的完整旅程)
4. [后端逐文件解读](#4-后端逐文件解读)
5. [Agent：最核心的部分](#5-agent最核心的部分)
6. [TTS 流水线](#6-tts-流水线)
7. [前端逐文件解读](#7-前端逐文件解读)
8. [测试是怎么写的](#8-测试是怎么写的)
9. [开发中真实踩过的坑](#9-开发中真实踩过的坑)
10. [和开发计划的对照：做了什么、没做什么](#10-和开发计划的对照做了什么没做什么)
11. [动手练习](#11-动手练习)

---

## 1. 先把项目跑起来

### 1.1 准备依赖

| 依赖 | 怎么装 | 说明 |
|---|---|---|
| Python 3.12（arm64） | 你已有：`/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12` | |
| uv | `python3.12 -m pip install --user uv`，然后把 `~/Library/Python/3.12/bin` 加进 PATH | Python 依赖管理 |
| Node.js 22 | 你已有 | |
| ffmpeg | 你已有（`/usr/local/bin/ffmpeg`） | 转 mp3、响度标准化 |
| F5-TTS | 你已部署在 `~/Documents/LLMWorkSpace/F5-TTS` | |

**不需要 Redis 和 Postgres**：默认用 SQLite 文件（`server/echo.db`），任务在 API 进程里执行。

### 1.2 第一次启动

```bash
make setup     # 生成 server/.env（含随机 JWT_SECRET）、装依赖、建表、写入音色

# 每个服务开一个终端
make f5        # F5-TTS
make api       # http://127.0.0.1:8000/docs，任务也在这个进程里执行
make web       # http://localhost:3000
```

### 1.2.2 语音聊天（本地 Qwen3.5-4B）

```bash
make ollama        # 启动本地大模型服务（后台运行）
make ollama-pull   # 第一次：下载 Qwen3.5-4B，约 3.4GB
```

然后打开 `http://localhost:3000/chat`，用中文或英文聊天，回复会自动用 F5 朗读出来。
所有大模型文件都放在 `~/Documents/LLMWorkSpace/Ollama/`：程序在 `bin/`，模型在 `models/`，日志在 `logs/`。

### 1.2.1 两种运行模式

| | 默认（本地开发） | 上线 |
|---|---|---|
| 数据库 | SQLite 文件 | Postgres：改 `DATABASE_URL` |
| 任务执行 | API 进程内（`MemoryQueue`） | 独立 Worker（`ArqQueue` + `make worker`） |
| 进度推送 | SSE 每 0.5 秒查数据库 | Redis pub/sub |
| 每日次数限制 | 数数据库里当天的任务 | Redis 计数 |
| 切换方式 | `REDIS_URL` 留空 | 填 `REDIS_URL` |
| 限制 | API 只能开一个进程 | 可以多进程、多机器 |

业务代码完全一样，区别只在 `main.py` 的 `lifespan` 里创建了哪个队列。这就是把队列抽象成 `JobQueue` 接口的好处。

打开 `http://localhost:3000`，注册账号（送 300 额度），选"我有文案，直接配音"，粘贴一段文字，点击开始，就能看到逐句的合成进度，完成后可以播放和下载。

**想先不开 F5？** 在 `.env` 里设置 `TTS_PROVIDER=mock`，合成出来的是提示音，但整条链路（排队、进度、拼接、字幕、计费）都是真实运行的，适合调前端。

### 1.3 配置中文音色（一定要做）

不配的话，`seed-voices` 会用 F5 自带的**英文**示例音色，合成中文会带外国口音。做法：

1. 在安静的环境下录 2–4 段 5–10 秒的中文录音，保存成 wav，放到 `server/voices/` 目录（这个目录建议加进 `.gitignore`）
2. `cp voices.example.json voices.json`，填好每段录音的路径和**逐字一致的原文**
3. 重新执行 `uv run python -m app.cli seed-voices`

也可以用命令单独添加一个：
```bash
uv run python -m app.cli add-voice --name 沉稳男声 --audio voices/calm.wav --text "录音里念的原文" --tags 沉稳,男声
```

### 1.4 常用管理命令

```bash
uv run python -m app.cli codes --credits 100 --count 10   # 生成 10 个 100 额度的兑换码
uv run python -m app.cli stats --days 7                   # 最近 7 天：任务数、模型花费、缓存命中率
```

### 1.5 跑测试

```bash
cd server && uv run pytest -q          # 78 个测试，约 12 秒，不需要 Postgres/Redis/F5/Claude
# 在真实 Postgres 上再跑一遍：
TEST_DATABASE_URL=postgresql+asyncpg://echo:echo@127.0.0.1:5432/echo uv run pytest -q
```

---

## 2. 推荐的阅读顺序

由内到外：先看数据长什么样，再看业务规则，最后看接口和界面。

| 顺序 | 文件 | 看什么 |
|---|---|---|
| 1 | `server/app/models.py` | 9 张表（含聊天的 2 张），理解数据长什么样 |
| 2 | `server/app/schemas.py` | API 的输入输出 |
| 3 | `server/app/services/jobs.py` | 状态机、创建任务、追问、取消 |
| 4 | `server/app/services/billing.py` | 额度账本 |
| 5 | `server/app/services/pipeline.py` | 任务从开始到结束的完整流程 |
| 6 | `server/app/agent/` | **Agent，重点** |
| 7 | `server/app/tts/` | 文本规整、分句、拼接、字幕 |
| 8 | `server/app/worker.py`、`main.py` | 进程怎么启动、资源怎么管理 |
| 9 | `server/app/api/jobs.py` | 接口，特别是 SSE |
| 10 | `web/lib/` → `web/app/(app)/jobs/[id]/` | 前端 |
| 11 | `server/tests/test_agent.py` | 看测试是怎么"不花钱"测 Agent 的 |

---

## 3. 一个请求的完整旅程

以"需求模式"为例，从用户点击按钮到听到声音，代码依次经过这些地方：

```
① 浏览器  web/app/(app)/studio/page.tsx  create.mutate()
          └─ fetch POST /api/jobs（同源请求，带 Cookie）

② Next.js web/next.config.ts  rewrites
          └─ 转发到 http://127.0.0.1:8000/api/jobs

③ FastAPI server/app/api/jobs.py  create_job()
          ├─ Depends(current_user)  → deps.py 解析 Cookie 里的 JWT
          ├─ Pydantic 校验 CreateJobIn
          └─ services/jobs.py  create()
               ├─ _check_limits()     并发数 + 每日次数
               ├─ INSERT jobs
               ├─ billing.hold()      锁用户行，预扣额度，写账本
               ├─ events.emit("created")   写事件表 → commit → Redis publish
               └─ _enqueue()          commit 之后才入队 → arq
          返回 202 + 任务 JSON

④ 浏览器跳转到 /jobs/{id}
          ├─ useJob()        GET /api/jobs/{id}，每 5 秒兜底刷新
          └─ useJobEvents()  EventSource → GET /api/jobs/{id}/events（SSE 长连接）

⑤ Worker  server/app/worker.py  run_job()
          └─ services/pipeline.py  run()
               ├─ _lock_job()        重新读取并锁住任务，检查是否已取消
               ├─ _write_script()    → agent/loop.py  run_agent()
               │     └─ 循环：调 Claude → 执行工具 → 发回结果 → … → finish
               ├─ _synthesize()      逐句：规整 → 查缓存 → F5 合成 → 存缓存
               ├─ _finalize_audio()  拼接 → 响度标准化 → mp3 → 字幕 → 存储
               ├─ billing.settle()   释放预扣，按实际时长扣费
               └─ transition(succeeded)
          每一步都 emit 事件 → Redis → SSE → 浏览器进度条

⑥ 浏览器收到 succeeded 事件 → 刷新详情 → 显示播放器
          └─ GET /api/jobs/{id}/file?format=mp3（FileResponse，支持 Range 拖动）
```

**看懂这张图，整个项目就看懂了一半。** 下面按文件逐个讲。

---

## 4. 后端逐文件解读

### 4.1 `app/config.py`：配置

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=SERVER_DIR / ".env", extra="ignore")
    jwt_secret: str = Field(min_length=32)
```

- `BaseSettings` 会自动从环境变量和 `.env` 读取同名字段（不区分大小写）：环境变量 `JWT_SECRET` 对应字段 `jwt_secret`
- `jwt_secret` **故意不设默认值**，并要求至少 32 位。没配置就启动失败，这样不可能带着弱密钥上线。32 这个数字来自 PyJWT 的警告：HS256 算法的密钥短于 32 字节是不安全的（测试时真的触发过这个警告）
- `env_file` 用绝对路径（`SERVER_DIR / ".env"`），不管从哪个目录启动都能找到配置文件
- `llm_fallbacks` 开关的用途：你的环境设置了 `ANTHROPIC_BASE_URL`，请求会经过一个代理网关，有些网关不认识 beta 参数会返回 400，这时可以关掉它

### 4.2 `app/db.py`：数据库连接

```python
engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

- **engine** 是全局唯一的连接池，**session** 是一次"工作单元"（一个请求或一个任务用一个 session）
- `expire_on_commit=False`：默认情况下，commit 后对象的所有属性都会"过期"，下次访问时重新查询数据库。在异步模式下，这种隐式查询会直接报错（`MissingGreenlet`），所以必须关掉
- SQLite 分支：本地开发和测试使用。文件库每个会话用自己的连接（内存库才用 `StaticPool` 共用一个连接），`WAL` 模式让读写互不阻塞；`PRAGMA foreign_keys=ON` 是因为 SQLite **默认不执行外键约束**，不打开的话，级联删除在测试里就测不出问题

### 4.3 `app/models.py`：数据表

**几个跨数据库的技巧**（让同一套模型在 Postgres 和 SQLite 上都能用）：

```python
JSONType = JSON().with_variant(JSONB(), "postgresql")
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")
```

- `with_variant` 的意思是：默认用前一个类型，遇到某种数据库时换成后一个。生产环境用 Postgres 的 JSONB（可以建索引、查询更快），测试用 SQLite 的 JSON
- SQLite 只有 `INTEGER PRIMARY KEY` 才会自增，`BIGINT` 不行，所以要单独处理

**时间戳为什么由 Python 生成**（`models.py:51`）：

```python
def utcnow_col(*, onupdate: bool = False, **kw):
    return mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now(), ...)
```

最初我用的是数据库的 `now()`，结果分页测试失败了：SQLite 的 `now()` 只精确到秒，同一秒内创建的 5 个任务时间戳完全一样，按时间排序就不稳定了。改成 Python 生成带微秒的 UTC 时间后，问题就解决了。见第 9 节第 2 条。

**`eager_defaults`**（`Base` 类上）：插入数据后，让数据库把它生成的值一并返回（Postgres 用 `RETURNING` 实现）。不加的话，`created_at` 这类字段在插入后处于"未加载"状态，接口返回数据时去读它，就会触发 `MissingGreenlet`。见第 9 节第 1 条。

**表设计要点**：
- `Job.agent_messages`：Agent 的完整对话。**只追加，不修改**（原因见第 5 节）
- `Job.pending_input`：Agent 追问时，暂存"问了什么"和"同一轮里其他工具的结果"
- `Job.enqueue_count`：第几次入队，用来生成 arq 的任务 ID（见 4.8）
- `Voice.deleted_at`：**软删除**。历史任务还引用着这个音色，真删的话，外键约束会阻止删除，而且"改一句重新生成"也没法用了
- `CreditLedger`：只追加的流水。任何时候都可以用 `SUM(delta)` 核对余额，测试里就是这么验证的
- `JobEvent.id` 全局自增，直接作为 SSE 的事件 ID 使用，断线续传就靠它

### 4.4 `app/errors.py` 和 `main.py` 里的统一错误处理

业务代码里只需要 `raise NotFound("任务不存在")`，`main.py` 的 `exception_handler` 会把它统一转成：

```json
{"error": {"code": "not_found", "message": "任务不存在"}}
```

参数校验错误（422）也被改成了同样的格式，并且把 Pydantic 的英文前缀 `Value error, ` 去掉了，前端可以直接把 `message` 显示给用户。

还有两个**不是 HTTP 错误**的异常：
- `TransientError`：临时错误（F5 没响应、模型限流），Worker 会安排重试
- `JobCanceled`：任务执行中被用户取消，流水线安静退出就行

### 4.5 `app/security.py` 和 `app/deps.py`：认证

```python
_hasher = PasswordHash.recommended()     # Argon2
```

**为什么用 Argon2 而不是 MD5 / SHA256**：MD5、SHA256 计算太快，数据库泄露后，攻击者每秒能试几十亿个密码。Argon2 是故意设计得很慢、而且很吃内存的算法，暴力破解的成本高出几个数量级。

`deps.py` 的 `current_user` 是一个 **FastAPI 依赖**：

```python
async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
```

路由函数只要声明 `user: User = Depends(current_user)` 就能拿到当前用户，不需要自己解析 Cookie。依赖可以嵌套：`current_user` 本身又依赖 `get_db`，FastAPI 会在一个请求内复用同一个 session。

同时支持 **Cookie**（浏览器）和 **Bearer Token**（以后的 iOS App），注册和登录接口都会返回 token，就是为 iOS 准备的。

`api/auth.py` 里 Cookie 的三个安全属性：
- `httponly=True`：JS 读不到，即使页面被注入恶意脚本（XSS），也偷不走登录态
- `samesite="lax"`：别的网站发起的请求不会带上这个 Cookie，防止跨站请求伪造（CSRF）
- `secure=settings.is_prod`：生产环境只通过 HTTPS 传输

登录失败时，不管是"用户不存在"还是"密码错误"，都返回同样的提示，防止别人借此探测哪些邮箱注册过。

### 4.6 `app/services/jobs.py`：任务的状态机

**状态流转表**（`jobs.py:28`）：

```python
ALLOWED = {
    S.queued: {S.writing, S.synthesizing, S.failed, S.canceled},
    S.writing: {S.needs_input, S.synthesizing, S.failed, S.canceled},
    ...
    S.succeeded: set(),     # 终态，不能再变
}
```

所有状态变化都通过 `transition()`，它做三件事：校验流转合法、修改状态、发出 `status_changed` 事件。**这是整个项目里最值得学的模式之一**：状态一多，如果到处直接写 `job.status = ...`，很快就会出现"已经成功的任务又变回合成中"这种 bug。

**越权校验**（`jobs.py:57`）：

```python
async def get_owned(db, user, job_id):
    job = await db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise NotFound("任务不存在")
```

别人的任务也返回 404，而不是 403，这样不会泄露"这个 ID 存在"这一信息。所有 `/jobs/{id}` 类接口都先调用它，`test_cannot_access_others_job` 测试了 4 个接口。

**游标分页**（`jobs.py:77`）：

```python
stmt.where((Job.created_at < ts) | ((Job.created_at == ts) & (Job.id < jid)))
    .order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)
```

- 为什么不用 `OFFSET`：翻页过程中如果有新任务插入，OFFSET 分页会出现重复或漏掉某些条目；游标分页从"上一页最后一条"往后取，不受影响
- 为什么要 `(created_at, id)` 两个字段：时间戳可能相同，加上 id 才能保证唯一的顺序
- `limit + 1`：多取一条，用来判断还有没有下一页，省掉一次 `COUNT` 查询

**创建任务的事务顺序**（`jobs.py:123`）是第 3 节流程图里的关键一步：
1. `db.add(job)` + `flush()`：把 INSERT 发给数据库但不提交，这样后面写账本时外键能引用到这条任务
2. `billing.hold()`：在**同一个事务**里扣额度
3. `events.emit()`：内部会 commit，任务、扣费、事件三者一起生效，要么全部成功，要么全部不生效
4. `_enqueue()`：**commit 之后**才放进队列

### 4.7 `app/services/billing.py`：额度账本

规则：预扣（hold）→ 成功后结算（release 再 charge），失败或取消时只做 release。每个函数都是**幂等**的，比如 `release` 开头会检查 `credits_held <= 0`，已经退过就不会重复退。

**`_locked_user` 的行锁**（`billing.py:40`）是这个项目里最有意思的 bug，详见第 9 节第 3 条：

```python
user = await get_for_update(db, User, user_id, key_share=True)   # db.py 里的封装
```

- `with_for_update`：生成 `SELECT ... FOR NO KEY UPDATE`，锁住这一行，其他事务想改它就得等着，扣费就变成了串行执行，余额不会被扣成负数
- `key_share=True`：用 `NO KEY UPDATE` 而不是 `UPDATE` 级别的锁，原因是它和外键检查不冲突，可以避免死锁
- `populate_existing=True`：session 里可能缓存着这个 user 的旧数据，这个参数强制用加锁后查到的最新值覆盖

`settle` 里有一个产品决策：如果实际时长超过了预估，**最多只扣预扣的额度**，超出部分由平台承担。这样用户看到的预扣额，就是他最多会付的钱。

### 4.8 `app/services/queue.py`：入队

```python
await self.pool.enqueue_job("run_job", job_id, _job_id=f"{job_id}:{attempt}")
```

`_job_id` 用来让 arq 去重：同一个 ID 不会被重复入队。但有个细节：**arq 会把任务结果保留一段时间**（`keep_result=3600` 秒），这期间同一个 `_job_id` 就无法再次入队。"回答追问后继续执行"需要把同一个任务再放进队列一次，所以 ID 里要带上第几次入队（`attempt`）。

为什么要包一层 `JobQueue` 接口：测试里换成 `FakeQueue`，它只记录入队了什么，测试再手动调用流水线来"模拟 Worker"。这样测试就不需要真的 Redis 和 Worker 进程。

### 4.8.1 `app/services/memory_queue.py`：不用 Redis 的队列

一个 `asyncio.Queue` 加一个后台协程，一次跑一个任务，正好符合 F5 只能串行的限制。要点：

- **重启不丢任务**：队列在内存里，但任务状态在数据库里。启动时 `_recover()` 把没做完的任务重新入队，已合成的句子命中缓存
- **重试不堵队列**：临时错误用 `call_later` 到点再放回队列，等待期间后面的任务照常执行
- **超时**：`asyncio.timeout` 到点取消任务，标记失败并退款
- **停止**：`CancelledError` 不是 `Exception` 的子类，不会被流水线的 `except Exception` 当成失败，任务保持未完成状态，下次启动接着做
- 执行和重试的规则在 `services/runner.py`，和 arq Worker 共用

### 4.8.2 SQLite 没有行锁怎么办

`db.py` 的 `get_for_update()`：Postgres 上是 `SELECT ... FOR UPDATE`；SQLite 会忽略它，所以先执行一条不改任何数据的 `UPDATE` 拿到整库写锁。代价是**写事务必须短**，所以流水线在等模型、等 F5 之前都会先 `commit`。

### 4.9 `app/services/events.py`：进度事件

```python
async def emit(db, redis, job_id, type_, payload):
    db.add(JobEvent(...))
    await db.commit()                    # 1. 先落库（可靠）
    await redis.publish(channel, ...)    # 2. 再广播（实时）
```

**为什么要两条路**：Redis pub/sub 是"发了就忘"，没人订阅或者断线了，消息就丢了。数据库是可靠的但不实时。两者结合：实时性靠 Redis，可靠性靠数据库。广播失败时只是吞掉异常，因为前端下次重连时会从数据库补齐。

注意 `emit` 内部会 commit，所以**它同时也是"提交点"**：之前对 job 的修改，会和这条事件一起提交。流水线里大量利用了这一点。

### 4.10 `app/services/pipeline.py`：流水线

这个文件是整个后端的"总调度"，请对照第 3 节流程图的第 ⑤ 步来读。

**异常处理的分层**（`pipeline.py:64` 的 `run()`）：

| 异常 | 处理方式 | 例子 |
|---|---|---|
| `NeedsInput` | 保存问题，状态改为 `needs_input` | Agent 要问用户 |
| `JobCanceled` | 安静退出（取消时已经退过款了） | 用户在合成途中点了取消 |
| `AgentError` | 标记失败 + 退款 | 模型拒绝、超过轮数、401 |
| `TransientError` | **回滚，抛给 Worker** | F5 没响应、模型 429 |
| 其他 `Exception` | 记录日志 + 标记失败 + 退款 | 代码 bug |

**`fail()` 的细节**：先 `rollback()`，丢掉失败前做了一半、还没提交的修改，再重新加锁读取任务、退款、标记失败。它可以被重复调用（已经是终态就直接返回）。

**取消检查**：`_ensure_not_canceled` 在每句合成前都查一次数据库。查询加了 `populate_existing`，否则 session 会返回缓存里的旧状态，永远发现不了取消。最后结算之前又锁了一次任务：如果这时任务已经被取消，就不再结算，因为取消时已经退过款了，再结算就会重复扣费。

### 4.11 `app/worker.py`：Worker 进程

```python
class WorkerSettings:
    functions = [run_job]
    max_jobs = 1          # F5 一次只能跑一个
    job_timeout = ...     # 15 分钟
    max_tries = 2
```

- 配了 `REDIS_URL` 才需要这个进程；没配时启动会直接提示并退出
- `on_startup` 里创建的 httpx 客户端、TTS、LLM 客户端等放进 `ctx`，所有任务共用，连接池可以复用
- `ctx["redis"]` 是 arq 自带的 Redis 连接，直接拿来 publish 进度
- **重试**：`TransientError` 且次数没用完时，`raise Retry(defer=15 * tries)`，第 1 次失败 15 秒后重试、第 2 次 30 秒后，这叫**退避**：如果是服务过载，马上重试只会让情况更糟。次数用完就标记失败并退款
- `shutdown` 用 `ctx.get("http")` 而不是 `ctx["http"]`，这是端到端测试时发现的 bug：startup 中途失败时 `http` 还没创建，shutdown 再报一个 `KeyError` 就会掩盖真正的错误原因

### 4.12 `app/main.py`：应用入口

**`lifespan`**：应用级资源（Redis 连接池、存储、httpx 客户端）在启动时创建一次，关闭时释放。这是 FastAPI 推荐的写法，旧教程里的 `@app.on_event("startup")` 已经被废弃了。

**`create_app(use_lifespan=False)`**：测试时不执行 lifespan，而是直接给 `app.state` 赋假实现。这就是"依赖注入"思想：代码依赖的是 `app.state.queue` 这个接口，具体是 arq 还是 FakeQueue，由外部决定。

**`/api/health`**：分别检查数据库、Redis、TTS，任何一项挂了就返回 503。部署后可以接入监控系统定时检查。

### 4.13 `app/api/jobs.py`：接口，重点是 SSE

**SSE 端点**（`jobs.py:73`）是最需要仔细看的接口：

```python
async def stream():
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)           # ① 先订阅
    history = await events_after(db, last_id) # ② 再回放历史
    for ev in history: yield ...
    while not await request.is_disconnected():
        msg = await pubsub.get_message(timeout=15)   # ③ 转发实时消息
        if msg is None: yield ": ping\n\n"           #    15 秒没消息就发心跳
        if data["id"] <= sent: continue              #    按 id 去重
```

1. **顺序是先订阅、再回放**。如果反过来，"回放完"和"开始订阅"之间产生的事件就会丢。先订阅的话，这段时间的事件会在订阅缓冲区里等着，可能和回放的事件重复，所以要按 id 去重
2. **心跳**：以 `:` 开头的行是 SSE 的注释，浏览器会忽略它，但它能防止中间的代理、负载均衡因为"连接空闲太久"把连接断开
3. **`retry: 3000`**：告诉浏览器断线 3 秒后自动重连
4. **不用 `Depends(get_db)`**：SSE 是长连接，可能持续几分钟，依赖注入的 session 会一直占着连接池里的一个连接。改成需要时临时开一个 session，用完立刻关闭
5. **`X-Accel-Buffering: no`**：告诉 Nginx 不要缓冲这个响应，否则进度会"攒一批才到"

**下载接口**：本地存储用 `FileResponse`，它**支持 Range 请求**（测试验证过返回 206）。浏览器播放音频、拖动进度条时会发 `Range: bytes=xxx-` 请求，不支持的话，在 Safari 上拖动进度条会失效。

### 4.14 `app/services/storage.py`：存储

- `LocalStorage` 的所有文件操作都用 `asyncio.to_thread` 包起来：`Path.write_bytes` 是阻塞调用，直接在 async 函数里调用会卡住整个事件循环，所有请求都会跟着变慢
- `S3Storage` 同理，boto3 是同步库
- `_safe_key` 防止路径穿越：如果有人构造出 `../../etc/passwd` 这样的 key，会被直接拒绝
- 生产环境用 S3 时，下载接口返回**预签名 URL** 并重定向过去，音频流量直接从对象存储走，不经过 API 服务器

---

## 4.15 语音聊天：本地模型 + F5 闭环

和写稿 Agent 是两条独立的功能，聊天只用本地 Ollama，**不需要 Claude**。

| 文件 | 作用 |
|---|---|
| `llm/ollama.py` | 调 Ollama 的 `/api/chat`，流式读取回复 |
| `services/chat.py` | 存消息 → 调模型 → 逐句合成语音 → 拼接 |
| `api/chat.py` | 会话和消息接口；发消息直接返回一条 SSE 流 |
| `web/lib/chatStream.ts` | 前端用 fetch 读取 POST 返回的 SSE 流 |
| `web/app/(app)/chat/page.tsx` | 聊天页面 |

**一条消息的流程**：

```
POST /api/chat/sessions/{id}/messages  {"text": "Hello"}
  ├─ event: user_saved      用户消息存库
  ├─ event: delta × N       Qwen 一边生成一边推（打字机效果）
  ├─ event: text_done       回复完整，存库
  ├─ event: audio_progress  每合成完一句推一次（1/5、2/5……）
  ├─ event: ping            没有进度时每 10 秒一次心跳
  ├─ event: audio           F5 逐句合成并拼接完成，前端自动播放
  └─ event: done
```

**几个设计点**：

1. **为什么用原生 `/api/chat` 而不是 OpenAI 兼容接口**：Qwen3.5 默认会先"思考"再回答，聊天时这段思考只会拖慢速度。关闭它的 `think: false` 参数只有原生接口认，兼容接口会忽略。
2. **为什么先出文字、再合成语音**：模型生成和 F5 合成都要用 GPU，同时跑会互相拖慢；而且 F5 一次只能合成一句。先出文字，用户马上就能看到回复，体验也好。
3. **为什么 POST 也能用 SSE**：浏览器自带的 `EventSource` 只支持 GET，所以前端改用 `fetch` 读取响应流，再自己按"空行分隔、`event:` / `data:` 开头"的格式解析（`chatStream.ts`）。
4. **英文不能套用中文规整规则**：之前的 `normalize()` 会把 "I have 3 cats" 变成 "I have 三 cats"。现在先判断句子里有没有中文字符，没有就只做最基本的清理。分句也补上了英文规则：`.` `!` `?` 后面跟空格才切，这样不会把 `3.5` 切开。
5. **全进程共用一个 TTS 实例**：配音任务和聊天都要调用 F5，如果各自创建一个 F5 客户端，就各有一把锁，两边会同时去调 F5。现在 `main.py` 只创建一个实例，所有调用方共用。
6. **系统提示词要求回复短、只用纯文本**：回复要念出来，太长会等很久，Markdown 符号也会被念出来。此外后端最多只合成前 6 句。
7. **每次只带最近 10 轮对话**（`CHAT_HISTORY_TURNS`），控制速度和显存。
8. **回复语言跟着用户"这一句"走**：小模型容易跟着历史的语言走（前面聊英文，用户改说中文它还回英文，实测遇到过）。所以每次请求都按用户这句话的语言，在系统提示里写明"Reply in Chinese / English"。
9. **合成在独立任务里跑**：先启动合成任务，再推送文字。前端任何时候断开，语音都会合成完并存库，回到页面还能播放。

**实测（M3 Pro，Qwen3.5-4B + F5）**：首字约 0.3 秒，一句回复 1～2 秒写完；语音每句约 8～10 秒，5 句的英文回复约 40 秒。

**以后可以加的**：语音输入（用 Whisper 识别你说的话，形成"说话 → 回复 → 朗读"的完整语音对话）、边生成边按句合成（缩短等待时间）、英语陪练专用的提示词（纠错、打分）。

## 5. Agent：最核心的部分

### 5.1 三个文件的分工

| 文件 | 职责 |
|---|---|
| `agent/prompts.py` | 系统提示词，**固定字符串** |
| `agent/tools.py` | 工具定义（给模型看的 JSON Schema）+ 工具实现（Python 代码） |
| `agent/script_check.py` | 文案检查：纯代码计算字数、时长、违禁词 |
| `agent/loop.py` | 主循环 |

### 5.2 为什么"检查稿件"要写成工具，而不是让模型自己检查

让模型自己数"这段话有多少字"，它经常数错。而 `count_units()` 一行正则就能数准，还不花钱。原则是：**规则明确的事情交给代码，需要判断的事情交给模型**。Agent 的价值在于"根据检查结果决定怎么改"，而不是"数字数"。

### 5.3 提示词为什么必须是固定字符串

请求是按 `tools → system → messages` 的顺序拼接的，**提示缓存按前缀匹配**。`loop.py` 在 system 末尾打了一个缓存断点：

```python
system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
```

这样 tools + system 这一大段内容第一次请求时写入缓存，后面每一轮都按缓存价计费（约为原价的十分之一或更低）。只要 system 里混进了"当前时间"或"用户名"这类会变的内容，前缀就变了，缓存就全部失效。所以会变的内容（需求、目标时长）都放在 `messages` 里。

怎么验证缓存是否生效：`uv run python -m app.cli stats` 会显示缓存命中率。如果它一直是 0%，就说明有东西让缓存失效了。注意，前缀太短也不会触发缓存，不同模型的最低长度在 512 到 4096 Token 之间。

### 5.4 主循环逐段解读（`loop.py:83`）

```python
messages = list(job.agent_messages or [])
if not messages:
    messages.append({"role": "user", "content": brief_message(...)})
```
如果是从追问中恢复的任务，`agent_messages` 里已经有完整的历史对话，接着往下跑；如果是新任务，就从用户的需求开始。

```python
for _turn in range(settings.llm_max_turns):
    resp = await call_model(llm, messages)
    await record_usage(db, job.id, resp)
```
**限制轮数**，防止模型陷入死循环、无限烧钱。每一轮都记录用量。

```python
    if resp.stop_reason == "refusal": raise AgentError(...)
    if resp.stop_reason in ("max_tokens", "model_context_window_exceeded"): raise AgentError(...)
```
**先检查停止原因，再读内容。** `refusal` 表示被安全策略拒绝（返回的 HTTP 状态码仍然是 200，不会抛异常，必须自己检查）。

```python
    messages.append({"role": "assistant", "content": _dump_content(resp.content)})
```
**把模型返回的每个块都原样追加回去**，包括 `thinking` 块。这里有两条规则：
1. thinking 块必须原封不动地传回去，不能删、不能改
2. **对话历史只追加、不修改**：如果修改了中间某一轮的内容，后面所有的 thinking 块都会失效，缓存也会失效

`test_agent_happy_path` 专门验证了这一点：第 3 轮请求的前缀和第 2 轮的完全一致。

```python
    tool_uses = [b for b in resp.content if b.type == "tool_use"]
    if not tool_uses:
        messages.append({"role": "user", "content": NUDGE_FINISH})
        continue
```
模型没有调用工具、只回了一段文字，就提醒它用 `finish` 提交。为什么不直接接受这段文字作为稿件：因为工具参数是结构化的（分段、停顿、音色、语速），纯文字还得自己再解析一遍，不可靠。

```python
    for tu in tool_uses:
        try:
            out = await run_tool(tu.name, tu.input, ctx)
        except ToolInputError as e:
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": str(e), "is_error": True})
            continue
```
**参数不合法时，不要直接报错退出，而是告诉模型哪里错了。** `is_error: True` 让模型知道这次调用失败了，它通常会在下一轮自己改正。`test_agent_bad_input_is_returned_as_error` 测的就是这个：第一次传了语速 5.0（超出范围），第二次模型改成了 1.0。

```python
    messages.append({"role": "user", "content": results})
```
**同一轮的所有 tool_result 放在同一条 user 消息里。** 模型可能一次调用多个工具（并行调用），如果把结果拆成多条消息发回去，模型会逐渐"学会"不再并行调用。

### 5.5 strict 模式和 Pydantic 校验的分工

```python
{"name": "finish", "strict": True, "input_schema": {..., "additionalProperties": False}}
```

`strict: True` 保证模型给出的参数**结构和类型**一定正确：该有的字段都有、类型对、没有多余字段。但它管不了：
- 数值范围（语速必须在 0.7 到 1.5 之间）
- 业务规则（这个音色是不是该用户可以用的、用户是否指定了别的音色）

所以 `tools.py` 里还有一层 Pydantic 校验（`FinishInput` 等模型），`finish` 工具里还会再检查一次违禁词。**模型的输出一律当作不可信的外部输入来处理。**

### 5.6 可暂停的 Agent：追问流程

这是 Agent 设计里比较难的部分，跟着测试 `test_agent_ask_user_pauses_and_resumes` 来看：

1. 模型在同一轮里调用了 `list_voices` 和 `ask_user`
2. `list_voices` 正常执行，结果放进 `results`；`ask_user` 的结果**暂时没有**（要等用户回答）
3. 抛出 `NeedsInput`，流水线把 `{tool_use_id, questions, results}` 存进 `job.pending_input`，状态改为 `needs_input`，Worker 结束这次执行
4. 用户在页面上回答，调用 `POST /answer` 接口，进入 `services/jobs.py` 的 `answer()`：
   ```python
   results = list(pending["results"])
   results.append({"type": "tool_result", "tool_use_id": pending["tool_use_id"], "content": text})
   job.agent_messages = [*job.agent_messages, {"role": "user", "content": results}]
   ```
   把用户的回答作为 `ask_user` 的工具结果，和 `list_voices` 的结果**合并成一条消息**追加到对话末尾（还是"同一轮的结果放一条消息"这个规则）
5. 重新入队，Worker 读取 `agent_messages` 后接着循环

关键点：**Agent 的"状态"完全保存在数据库里的对话记录中**，Worker 进程本身不保存任何状态。所以暂停多久都没关系，Worker 重启了也不影响。

**`job.agent_messages = list(messages)`，为什么每次都要整体赋值**：SQLAlchemy 是通过"属性被重新赋值"来判断 JSON 列有没有变化的。原地 `append` 不会触发赋值，修改就不会被保存到数据库。

### 5.7 `call_model` 的参数（`loop.py:57`）

| 参数 | 作用 |
|---|---|
| `model=settings.llm_model` | 默认 `claude-opus-5-5`，改配置就能换模型 |
| `max_tokens=16000` | 单次输出上限（包括思考过程） |
| `thinking={"type": "adaptive"}` | 自适应思考：模型按题目难度自己决定想多少。新一代模型不再支持固定的 `budget_tokens`，传了会报 400 |
| `output_config={"effort": "medium"}` | 控制思考深度和 Token 消耗的主要旋钮。写口播文案用 medium 就够了；效果不好再调高，想省钱就先在评测集上试试 low |
| `fallbacks="default"` + beta 头 | 正常请求偶尔会被安全分类器误判拒绝，开启后服务端会自动换一个模型重试 |
| 没有 `tool_choice` | 新模型不支持强制指定调用某个工具（会报 400），所以用 `auto` + 提示词要求 + `strict` 来达到同样的效果 |
| 没有 `temperature` | 新模型已经移除了采样参数 |

**错误分类**：
- `RateLimitError`、`APIConnectionError`、`InternalServerError` 转成 `TransientError`，由 Worker 重试。SDK 内部已经自动重试过 3 次，到这一步说明问题持续了一段时间
- 其他 `APIStatusError`（400、401、403）转成 `AgentError`，直接失败，因为请求本身有问题，重试没用

**我在你机器上验证过的**：用拦截器截获了 SDK 实际发出的请求，确认请求体里的 `thinking`、`output_config`、`fallbacks`、`strict` 都正确，thinking 块也被原样传回。真实调用时返回了 401，原因是当前环境里的 API Key 对你配置的代理网关无效（见第 10 节）。

---

## 6. TTS 流水线

### 6.1 `tts/text_norm.py`：文本规整

规则的**顺序很重要**，每条都有对应的测试（`tests/test_text_norm.py`）：

1. 读音词典最先执行（用户的自定义读音优先级最高），按**词长从长到短**替换。不然 "AppStore" 会先被 "App" 的规则替换成 "A P PStore"
2. 价格：`¥99` → `99元`
3. **百分比必须在通用数字规则之前处理**：`35%` → `百分之三十五`。如果先把数字转成汉字，就成了"三十五%"，再处理就困难了
4. 范围：`3-5天` → `3到5天`
5. 年份逐位读：`2025年` → `二零二五年`（而不是"两千零二十五年"）
6. 时间：`9:30` → `九点三十`
7. 5 位及以上的数字逐位读（电话号码、编号）：`10086` → `一零零八六`
8. 最后处理剩下的数字：`299` → `二百九十九`

规整后的文本只用于合成，字幕仍然显示原文。你可以在 F5 的日志里看到它实际收到的是规整后的文本。端到端测试时的日志：`今天是二零二六年十一月二十二日，价格只要九十九元！`

### 6.2 `tts/chunker.py`：分句

- 先按段落切，再按 `。！？；…` 切成句子
- 少于 6 字的短句并入前一句（"是吧？"这种单独合成会很怪）
- 超过 60 字的长句在逗号处再切
- 停顿：句末 400ms、段末 700ms、逗号处切开的 200ms，最后一句为 0

**`count_units` 必须前后端一致**：后端 `chunker.py` 和前端 `web/lib/format.ts` 各有一份同样的实现，前端用它实时显示"预计时长"。改了一边，记得同步改另一边。

### 6.3 `tts/audio.py`：拼接

```python
def concat(parts):  # [(wav_bytes, pause_ms)]
    for wav, pause_ms in parts:
        samples, sr = read_wav(wav)
        samples = _resample(samples, sr, rate)      # 采样率不一致就先重采样
        spans.append([start_ms, end_ms])           # 记录每段的起止时间
        chunks += [samples, np.zeros(静音长度)]
```

- **采样率不一致时，必须重采样后再拼接**，否则播放会变调（`test_concat_resamples_mismatched_rate`）
- `spans` 是字幕时间轴的来源，也是前端"播放时高亮当前句子"的依据
- `_ffmpeg()` 用**参数列表**调用子进程，不拼接 shell 命令字符串，可以防止命令注入；用 `pipe:0` 和 `pipe:1` 在内存中输入输出，不写临时文件
- `loudnorm`：把整段音频的响度标准化到 -16 LUFS（短视频平台常用的标准），避免句子之间音量忽大忽小

### 6.4 合成缓存（`pipeline.py:144`）

```python
raw = f"{text}|{voice_id}|{speed:.2f}|{provider}|{settings.tts_model_version}"
```

哈希里**包含模型版本号**：以后换了 F5 的模型，所有旧缓存自动失效，不会拿旧模型的声音冒充新模型。

`test_tts_cache_on_revise` 验证了这个效果：3 句话只改了 1 句，重新生成时只合成了 1 次（总调用次数从 3 变成 4）。

### 6.5 `tts/f5.py`：F5 适配器

- `asyncio.Lock()`：同一进程内的合成请求串行执行
- 输出文件名 `echo_{uuid}.wav` **由我们生成**，不使用任何用户输入，防止路径注入
- `ConnectError`、`ReadTimeout` 转成 `TransientError`，可以重试；HTTP 5xx 也算临时错误；4xx 就是我们自己的请求有问题了

**提醒**：F5 每合成一句，都会在 `F5-TTS/outputs/` 目录里留一个 `echo_*.wav` 文件（这是 `tts_server.py` 本身的行为）。我们已经把合成结果存进了自己的缓存，这些文件就没用了，需要定期清理，或者以后修改 `tts_server.py`，让它合成后删掉临时文件。

### 6.6 `tts/verify.py`：质检（M4，默认关闭）

用 ASR 把每句音频转回文字，计算和原文的字错误率（CER）。`cer()` 是一个标准的**编辑距离**动态规划算法，值得手推一遍。开启方法：`uv add mlx-whisper`，然后设置 `VERIFY_ENABLED=true`。目前只把可能读错的句子标出来，还没有做"让模型改写并重新合成"的闭环（见第 10 节）。

---

## 7. 前端逐文件解读

### 7.1 Next.js 16 的三个关键变化（这次真实踩到的）

1. **`middleware.ts` 改名为 `proxy.ts`**，导出的函数也叫 `proxy`
2. **动态路由的 `params` 是 Promise**，需要 `await params`（服务端组件）或 `use(params)`（客户端组件）
3. **`cacheComponents: true` 时，读取运行时数据的地方必须包在 `<Suspense>` 里**。运行时数据包括 `params`、`usePathname()`、`useSearchParams()` 等，不包的话，构建会直接报错。详见第 9 节第 4、5 条

### 7.2 `next.config.ts`

```ts
async rewrites() {
  return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
},
compress: false,
```

- **rewrites**：浏览器只访问 `localhost:3000`，`/api/*` 由 Next.js 在服务端转发给 FastAPI。浏览器看到的是同源请求，所以 Cookie 会自动带上，也不需要配置 CORS
- **`compress: false`**：开了 gzip 压缩，流式响应（SSE）会被中间层缓冲，进度条就不实时了。生产环境的压缩一般交给 Nginx 或 CDN 来做，在那一层把 `text/event-stream` 排除掉就行

### 7.3 `proxy.ts`

只检查"有没有 `echo_session` 这个 Cookie"，没有就跳转到登录页，并带上 `?next=` 参数，登录后跳回原来的页面。**它不校验 JWT 是否有效**，真正的鉴权在 FastAPI 里做。这就是官方文档说的"乐观检查"：Cookie 过期的用户会先进入页面，然后 API 返回 401。

登录页对 `next` 参数做了校验：`next?.startsWith("/")`，只允许跳转到站内地址，防止有人构造 `?next=https://钓鱼网站` 的链接（开放重定向漏洞）。

### 7.4 `lib/api.ts`

`fetch` 的薄封装：统一带上 Cookie（`credentials: "include"`）、统一解析后端的错误格式，抛出 `ApiError(status, code, message)`。上传文件时传入 `FormData`，此时**不设置 Content-Type**，让浏览器自动加上 multipart 的分隔符（boundary）。

### 7.5 `lib/hooks.ts`：数据层

**`useJob`**：

```ts
refetchInterval: (q) => (q.state.data && TERMINAL.includes(q.state.data.status) ? false : 5000),
```

任务进行中时每 5 秒兜底刷新一次，结束后停止。SSE 才是主要的更新方式，这里只是保险。

**`useJobEvents`**：SSE 订阅

```ts
const es = new EventSource(`/api/jobs/${jobId}/events`, { withCredentials: true });
es.addEventListener("progress", ...);
return () => es.close();
```

- 后端发送的事件名是 `event: progress`，所以要用 `addEventListener("progress")` 监听，`onmessage` 只能收到没有指定事件名的消息
- 收到状态变化类事件时，调用 `invalidateQueries` 让详情数据重新拉取。**不要手动修改缓存**，让服务器的数据作为唯一的数据来源
- 用 `seen` 按 id 去重：重连时，后端会从 `Last-Event-ID` 之后开始补发事件，但浏览器可能在断开前已经收到了其中一部分
- **清理函数里一定要 `es.close()`**。开启 `cacheComponents` 后，离开页面时组件不会被卸载，而是被隐藏，但 effect 会被清理。如果不关闭连接，SSE 就会一直连着

### 7.6 `app/(app)/jobs/[id]/`：任务详情页

拆成了两个文件：
- `page.tsx`（服务端组件）：`await params` 拿到 id，用 `<Suspense>` 包住
- `JobDetail.tsx`（客户端组件）：所有交互逻辑

**为什么要拆**：`cacheComponents` 模式下，Next.js 会先把页面的静态"外壳"预渲染出来，动态部分随后再流式传输过来。`params` 是动态数据，必须在 Suspense 边界里读取。

**播放时高亮当前句子**：

```ts
const activeIndex = job?.spans?.findIndex(([s, e]) => currentMs >= s && currentMs < e) ?? -1;
```

`AudioPlayer` 的 `timeupdate` 回调把当前播放时间传上来，然后在 `spans` 时间轴里找到对应的句子。点击某一句时，调用 `player.seek(spans[i][0])` 跳到那句的开头。

**这里没有用 `useMemo`**：项目开启了 React Compiler，它会自动做记忆化。手写的 `useMemo` 依赖数组和编译器推断的不一致时，lint 会直接报错（第 9 节第 6 条）。

### 7.7 `components/AudioPlayer.tsx`

- `ref` 直接作为普通 prop 传入：这是 React 19 的新写法，不再需要 `forwardRef`
- `useImperativeHandle` 只对外暴露 `seek` 和 `play` 两个方法，父组件拿不到 WaveSurfer 实例本身，封装更干净
- `onTimeRef`：把回调函数存进 ref。父组件每次渲染都会传入一个新的函数，如果把它放进 effect 的依赖数组，播放器就会被反复销毁重建
- **清理函数里一定要 `w.destroy()`**，否则切换页面后会叠出多个播放器，多份音频同时播放
- `fetchParams: { credentials: "include" }`：WaveSurfer 是自己用 fetch 加载音频的，要让它也带上 Cookie

### 7.8 `app/(app)/studio/page.tsx`：创作台

- `useForm` + `zodResolver(CreateJobSchema)`：表单校验规则写在 `lib/schemas.ts` 里，和后端的 `CreateJobIn` 一一对应
- `useWatch` 监听 mode、text 等字段，实时更新字数和预计时长
- 提交成功后先 `invalidateQueries(["me"])`（余额变了），再跳转到详情页

---

## 8. 测试是怎么写的

### 8.1 测试的整体设计（`tests/conftest.py`）

**原则：单元测试不依赖任何外部服务。**

| 真实依赖 | 测试中的替代 |
|---|---|
| Postgres | 临时文件 SQLite（设置 `TEST_DATABASE_URL` 可以切换成真实 Postgres） |
| Redis | `fakeredis`（支持 publish/subscribe、incr） |
| arq + Worker 进程 | `FakeQueue` + `run_worker()` 辅助函数，在测试里同步执行流水线 |
| F5 | `MockProvider`（生成提示音，并记录合成了哪些文本） |
| Claude | `FakeLLM`（按顺序返回预先准备好的响应） |
| 本地存储 | 临时目录，测试结束后删除 |

`conftest.py` 开头用 `os.environ.update(...)` 设置环境变量，**必须写在 `import app` 之前**，因为 `app.config` 在被导入时就读取了配置。

### 8.2 FakeLLM：不花钱测试 Agent（`tests/test_agent.py`）

```python
deps.llm = FakeLLM([
    msg(thinking(), tool("list_voices", {})),
    msg(tool("check_script", {...})),
    msg(tool("finish", {...})),
])
```

FakeLLM 模仿 SDK 的调用方式（`client.beta.messages.create(...)`），按顺序返回预设的响应，同时**记录每一次请求的内容**。测试就可以检查：
- 发给模型的参数对不对（thinking、缓存断点、模型名）
- 历史是不是只追加的（第 3 轮请求的前缀等于第 2 轮的）
- 工具结果有没有正确发回（`list_voices` 的结果里有那个音色的 ID）
- 错误参数有没有作为 `is_error` 返回给模型

响应对象用 SDK 自己的类型 `BetaMessage.model_validate(...)` 构造，保证和真实返回的结构完全一致。

### 8.3 Agent 测试覆盖的 7 种场景

| 测试 | 场景 |
|---|---|
| `test_agent_happy_path` | 查音色 → 检查稿件 → 定稿 → 合成成功 |
| `test_agent_bad_input_is_returned_as_error` | 语速超出范围 → 返回 is_error → 模型自己修正 |
| `test_agent_rejects_unknown_voice_and_banned_words` | 音色不存在、稿件包含违禁词，都被拦下 |
| `test_agent_ask_user_pauses_and_resumes` | 追问 → 暂停 → 用户回答 → 恢复执行 |
| `test_agent_refusal_fails_and_refunds` | 被安全策略拒绝 → 失败 + 退款 |
| `test_agent_max_turns` | 超过最大轮数 → 失败 |
| `test_agent_nudged_when_no_tool_call` | 只回了文字没调工具 → 提醒后继续 |

### 8.4 并发扣费测试（`tests/test_billing.py`）

8 个协程同时从 30 额度里各扣 10，断言**恰好有 3 个成功**、余额为 0、账本合计正好是 -30。SQLite 和 Postgres 上都会跑；在 Postgres 上，正是它发现了第 9 节第 3 条的死锁。

### 8.5 第一版实际运行的结果（当时还依赖 Redis）

- SQLite：50 个通过，1 个跳过（并发测试）
- 真实 Postgres 16：51 个全部通过，数据库迁移和模型定义一致（`alembic check` 通过）
- 前端：`tsc`、`eslint`、`next build` 全部通过
- 端到端：Next.js → FastAPI → arq Worker → 真实 F5 全部跑通。文案模式 2 句话 18 秒完成，生成了 8.7 秒的音频；SSE 进度、Range 请求、兑换码都验证过

---

## 9. 开发中真实踩过的坑

这些都是这次写代码时真实遇到的问题，每一条都是很好的学习材料。

### 坑 1：`MissingGreenlet`（异步 SQLAlchemy 最常见的错误）

**现象**：创建任务后，接口在返回数据时报错 `greenlet_spawn has not been called`。
**原因**：`updated_at` 是由数据库生成的值，插入之后 SQLAlchemy 并不知道它是多少，于是把它标记为"未加载"。Pydantic 序列化时去读这个属性，触发了一次隐式的数据库查询，而**异步模式下不允许隐式 IO**。
**解决**：在 `Base` 上加 `__mapper_args__ = {"eager_defaults": True}`，插入时让数据库通过 `RETURNING` 子句把生成的值一并返回。
**记住**：在异步 SQLAlchemy 里，任何"访问属性时才去查数据库"的行为都会报这个错。懒加载的关联对象要用 `selectinload` 提前加载。

### 坑 2：同一秒内创建的数据，分页结果出错

**现象**：连续创建 5 个任务，分页查询拿回来的结果有重复、也有遗漏。
**原因**：SQLite 的 `now()` 只精确到秒，5 个任务的 `created_at` 完全相同，排序不稳定。
**解决**：时间戳改为由 Python 生成（带微秒），排序时再加上 `id` 作为第二个排序字段。
**记住**：**不要用测试数据库的行为推断生产数据库的行为**。Postgres 的 `now()` 精确到微秒，所以这个 bug 在生产环境里很难复现，但同样存在于一些其他场景中（比如批量插入的数据会共享同一个事务时间戳）。

### 坑 3：并发扣费导致数据库死锁 ⭐

**现象**：并发测试在 Postgres 上报错 `deadlock detected`。
**原因**（这是一个经典问题）：
1. 事务 A 插入 `jobs` 表的一行：外键检查会对 `users` 表的对应行加 **KEY SHARE** 锁
2. 事务 B 同样插入一条 job，也对同一个用户行加了 KEY SHARE 锁（KEY SHARE 锁之间不冲突）
3. 事务 A 执行 `SELECT ... FOR UPDATE` 去锁这个用户行准备扣费，但 **FOR UPDATE 和 KEY SHARE 冲突**，只能等 B 释放
4. 事务 B 也执行 `FOR UPDATE`，同样要等 A 释放
5. 互相等待，形成死锁

**解决**：改用 `FOR NO KEY UPDATE`（`with_for_update={"key_share": True}`）。这个级别的锁和 KEY SHARE 不冲突，但它们彼此之间仍然互斥，扣费照样是串行执行的。我们只修改余额字段，不修改主键，用这个锁级别就够了。
**记住**：**外键也会加锁**。只要"先插入一条引用了某行的数据，再锁住被引用的那一行"，就要想到这个问题。另外，SQLite 上永远测不出这个 bug，并发相关的测试一定要在真实数据库上跑。

### 坑 4：Next.js 16 构建报错 "uncached or runtime data during prerendering"

**现象**：`npm run build` 报错，指向任务详情页读取 `params` 的那一行。
**原因**：`cacheComponents` 模式下，Next.js 会尽量把页面的"外壳"预渲染成静态 HTML。`params` 只有在请求到来时才知道，属于运行时数据，必须在 `<Suspense>` 里读取，这样外壳可以先返回，动态部分随后再流式补上。
**解决**：把详情页拆成两部分：服务端的 `page.tsx` 用 Suspense 包住一个读取 `params` 的组件，客户端组件 `JobDetail.tsx` 负责交互逻辑。构建结果里这个页面显示为 `◐ Partial Prerender`。

### 坑 5：同样的错误又出在导航栏上

**现象**：修完坑 4 后再次构建，这次报错指向 `NavBar` 里的 `usePathname()`。
**原因**：在动态路由下，`usePathname()` 的返回值也是运行时数据。
**解决**：在 `(app)/layout.tsx` 里用 `<Suspense>` 包住 NavBar，并提供一个**和导航栏等高的占位元素**，避免加载时页面跳动。

### 坑 6：React Compiler 和手写的 `useMemo` 冲突

**现象**：lint 报错 `Existing memoization could not be preserved`。
**原因**：项目开启了 React Compiler，它会自动分析依赖并做记忆化。我手写的依赖数组 `[job?.spans, currentMs]` 和编译器推断出的依赖不一致。
**解决**：去掉 `useMemo`，直接写普通的计算表达式，让编译器来处理。
**记住**：用了 React Compiler 的项目，基本不需要再手写 `useMemo` 和 `useCallback`。

### 坑 7：根目录 `.gitignore` 把 `web/lib/` 忽略了

**现象**：`web/lib/` 下的文件不出现在 `git status` 里。
**原因**：GitHub 生成的 Python 模板 `.gitignore` 里有一行 `lib/`（本意是忽略 Python 打包产生的目录），它会匹配**任意层级**的 lib 目录。
**解决**：改成 `/lib/`，只匹配仓库根目录下的 lib。
**记住**：在 monorepo（一个仓库里放多个项目）里使用语言模板的 `.gitignore` 时，要检查有没有这种"误伤"其他目录的规则。可以用 `git check-ignore -v 文件路径` 查出是哪条规则忽略了某个文件。

### 坑 8：arq 的任务 ID 去重导致无法重新入队

**现象**：如果用同一个 `_job_id` 重新入队，回答追问之后任务不会再执行。
**原因**：arq 会保留已完成任务的结果一段时间（`keep_result`），在此期间同一个 ID 的入队请求会被直接忽略。
**解决**：任务 ID 用 `{job_id}:{第几次入队}` 的格式。

### 坑 9：Worker 启动失败时，真正的错误被掩盖

**现象**：Worker 启动失败，日志最后一行显示 `KeyError: 'http'`。
**原因**：真正的错误发生在 `startup` 里，但 arq 随后会调用 `shutdown`，而 `shutdown` 里写的是 `ctx["http"]`，这个 key 此时还不存在，于是又抛出了一个新错误。
**解决**：改成 `ctx.get("http")`。
**记住**：**清理代码要能应对"初始化只做了一半"的情况**，否则真正的错误原因会被掩盖。

### 坑 11：Next.js 代理 30 秒超时，语音"丢了"

**现象**：聊天时文字正常出来，但较长的回复收不到语音，数据库里也没有存下音频。
**原因**：`next.config.ts` 的 rewrites 转发请求时，代理默认 30 秒超时（`next/dist/server/lib/router-utils/proxy-request.js` 里写死的 `proxyTimeout || 30000`）。F5 合成要 20～40 秒，这期间没有数据往外发，连接被代理断开；连接一断，后端的流式生成器也被取消，合成到一半的语音没来得及存库。
**解决**：三处一起改。① 后端合成期间每句推一次进度、没进度时每 10 秒推一次心跳；② `experimental.proxyTimeout` 调到 5 分钟；③ 合成放进独立的后台任务，前端断开也会合成完并存库。
**记住**：**任何"慢操作 + 流式返回"经过代理时都要考虑超时**，Nginx、云负载均衡也有类似的空闲超时（常见 60 秒）。心跳是通用解法。

### 坑 10：SDK 用的是 `httpx2` 而不是 `httpx`

**现象**：给 Anthropic SDK 传入自定义的 `httpx.AsyncClient` 时报错。
**原因**：这个版本的 SDK（2.12）内部改用了 `httpx2` 库。
**记住**：**不要凭记忆写 SDK 的用法**，以当前安装版本的源码和类型定义为准。这次写代码前，我也是先用 `inspect` 检查了 `beta.messages.create` 实际支持哪些参数（确认了 `fallbacks`、`output_config` 都在），才动手写调用代码的。

---

## 10. 和开发计划的对照：做了什么、没做什么

### 已完成并验证

| 里程碑 | 内容 | 验证方式 |
|---|---|---|
| M0 | uv 依赖管理、FastAPI、配置、健康检查、Alembic、Docker Compose、CI 配置、Makefile | 健康检查实测通过，`alembic check` 通过 |
| M1 | 文案直出全链路：任务队列、F5 合成、规整、分句、拼接、mp3、字幕、SSE | 真实 F5 端到端跑通 |
| M2 | 注册登录、Cookie + Bearer 认证、proxy.ts、越权校验、历史列表（游标分页）、删除 | 测试覆盖 |
| M3 | Agent 写稿、4 个工具、追问与恢复、用量记录 | FakeLLM 测试 7 种场景，并核对了 SDK 实际发出的请求体 |
| M4（部分） | 读音词典、改稿重新生成（命中缓存）、响度标准化、质检代码 | 前三项有测试覆盖；质检代码已写好，但没有安装 ASR 实际运行过 |
| M5 | 账本、预扣/结算/退款、兑换码、并发数和每日次数限制 | Postgres 上的并发测试通过 |
| M6（部分） | S3 存储实现、CI 配置 | **都没有实际运行过**，见下表 |

### 没做或没验证的（如实说明）

| 项目 | 状态 | 说明 |
|---|---|---|
| 需求模式调用真实 Claude | ❌ 没跑通 | 你环境里的 `ANTHROPIC_API_KEY` 访问代理网关（`ANTHROPIC_BASE_URL`）时返回 401。在 `server/.env` 里填一个有效的 key 就能用；如果网关不认识 `fallbacks` 参数，再设置 `LLM_FALLBACKS=false` |
| 本机的 Postgres / Redis | ⚠️ 用了替代品 | 本机没有 Docker，brew 安装也报错了。验证时 Postgres 用的是 `pgserver`（嵌入式 Postgres 16，真实数据库），Redis 用的是 fakeredis 的 TCP 模拟服务。真实 Redis 的行为没有测过 |
| CI | ⚠️ 没在 GitHub 上跑过 | 配置文件写好了，`uv sync --frozen` 在本地用干净环境模拟过；第一次推送后请去 Actions 页面看一下运行结果 |
| S3 存储 | ⚠️ 没跑过 | 代码已写好，用 MinIO 测试（`docker compose --profile s3 up -d`） |
| 质检（ASR） | ⚠️ 没跑过 | 需要先 `uv add mlx-whisper`；"读错的句子让模型改写后自动重新合成"这个闭环还没做 |
| 管理后台页面 | ❌ 没做 | 先用 `app.cli stats` 命令代替 |
| 微信 / 支付宝支付 | ❌ 没做 | 需要营业执照；目前用兑换码充值 |
| Sentry、结构化日志 | ❌ 没做 | |
| 前端自动化测试（Playwright） | ❌ 没做 | 前端只做了类型检查和构建验证，**页面没有在浏览器里实际点击测试过** |
| iOS App（M7） | ❌ 没做 | 后端已支持 Bearer Token |
| Agent 评测集 | ❌ 没做 | 拿到有效的 key 之后，这是最值得优先做的事 |

---

## 11. 动手练习

按难度从低到高，每做完一个都可以提交一次代码。

1. **读音规则**：给 `text_norm.py` 加一条规则，把 `1/2` 读成"二分之一"，同时在 `test_text_norm.py` 里加测试用例。（练习：正则 + TDD）
2. **违禁词**：往 `script_check.py` 里加几个词，再想想如何避免"最近"被"最"误判。（练习：业务规则设计）
3. **新的 SSE 事件**：在 `_finalize_audio` 开头发一个 `encoding` 事件，并在前端的 `describe()` 里显示"正在转码"。（练习：前后端联动）
4. **Agent 评测**：写 `tests/evals/run_eval.py`，用 10 条真实需求调用真实模型，统计时长误差、违禁词数、轮数和成本。（练习：AI 应用最重要的能力）
5. **换模型对比**：用评测脚本比较 `LLM_EFFORT=low` 和 `medium`，或者 Opus 和 Sonnet 的效果与成本，用数据做决定
6. **接入云端 TTS**：照着 `tts/f5.py` 写一个 `tts/doubao.py`，在 `factory.py` 里注册，然后改配置切换过去。（练习：理解接口抽象的价值）
7. **质检闭环**：读错的句子，让模型用 `client.beta.messages.parse()` 配合 Pydantic 模型改写成更容易朗读的写法，再重新合成，最多重试 1 次
8. **iOS 客户端**：用 SwiftUI 调用这套 API，SSE 部分用 `URLSession.bytes(for:)` 逐行读取
