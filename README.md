# 磷化氢暴露复核 JSON API

纯后端验收服务，使用 Python 3.12、FastAPI、Pydantic 与 pytest。服务对不等间隔采样读数进行分段直线插值，找出浓度不低于目标阈值的全部连续闭区间；只比较最长单一连续区间，不累计彼此分离的区间。

## 接口

`POST /verify`

请求示例：

```json
{
  "warehouse_id": "A-01",
  "threshold_ppm": 0.3,
  "minimum_duration_seconds": 0.02,
  "readings": [
    {"timestamp": "2026-09-13T08:00:00.000Z", "concentration_ppm": 0.1},
    {"timestamp": "2026-09-13T08:00:00.010Z", "concentration_ppm": 0.4},
    {"timestamp": "2026-09-13T08:00:00.030Z", "concentration_ppm": 0.4}
  ]
}
```

成功响应：

```json
{
  "warehouse_id": "A-01",
  "valid_intervals": [
    {
      "start_unix_ms": 1789286400007,
      "end_unix_ms": 1789286400030,
      "duration_ms": 23
    }
  ],
  "longest_duration_ms": 23,
  "qualified": true
}
```

`qualified` 仅由以下条件决定：

```text
longest_duration_ms >= minimum_duration_seconds × 1000
```

`POST /verify-conservative`

仪器存在已知测量偏差时的保守口径复核：请求在单测点请求基础上增加非负、有限且最多三位小数的 `measurement_error_ppm`。计算器先从每条读数浓度中扣除该误差上限（扣为负数时下限截为零），再沿用相同的插值、毫秒舍入与连续区间规则。

请求示例：

```json
{
  "warehouse_id": "A-01",
  "threshold_ppm": 0.3,
  "minimum_duration_seconds": 0.02,
  "measurement_error_ppm": 0.1,
  "readings": [
    {"timestamp": "2026-09-13T08:00:00.000Z", "concentration_ppm": 0.1},
    {"timestamp": "2026-09-13T08:00:00.010Z", "concentration_ppm": 0.4},
    {"timestamp": "2026-09-13T08:00:00.030Z", "concentration_ppm": 0.4}
  ]
}
```

成功响应与 `POST /verify` 完全同构（仓号、有效区间、最长持续毫秒数、`qualified`），仅追加回显本次使用的误差上限，原有响应解析无需改造：

```json
{
  "warehouse_id": "A-01",
  "valid_intervals": [
    {
      "start_unix_ms": 1789286400010,
      "end_unix_ms": 1789286400030,
      "duration_ms": 20
    }
  ],
  "longest_duration_ms": 20,
  "qualified": true,
  "measurement_error_ppm": 0.1
}
```

误差上限为负数、非有限数或超过三位小数时返回 422，错误定位到 `measurement_error_ppm`，且不产生任何暴露区间或判定。仓号、阈值、持续时长、时间戳与读数的全部校验规则与 `POST /verify` 一致。

`POST /verify-joint`

同一粮仓内两至十个测点的联合复核：各测点读数序列复用单测点的全部校验规则，且首末时间戳必须一致；测点编号在请求内必须唯一。

请求示例：

```json
{
  "warehouse_id": "A-01",
  "threshold_ppm": 0.3,
  "minimum_duration_seconds": 0.02,
  "points": [
    {
      "point_id": "P-1",
      "readings": [
        {"timestamp": "2026-09-13T08:00:00.000Z", "concentration_ppm": 0.1},
        {"timestamp": "2026-09-13T08:00:00.010Z", "concentration_ppm": 0.4},
        {"timestamp": "2026-09-13T08:00:00.030Z", "concentration_ppm": 0.4}
      ]
    },
    {
      "point_id": "P-2",
      "readings": [
        {"timestamp": "2026-09-13T08:00:00.000Z", "concentration_ppm": 0.5},
        {"timestamp": "2026-09-13T08:00:00.025Z", "concentration_ppm": 0.5},
        {"timestamp": "2026-09-13T08:00:00.030Z", "concentration_ppm": 0.1}
      ]
    }
  ]
}
```

成功响应：

```json
{
  "warehouse_id": "A-01",
  "point_ids": ["P-1", "P-2"],
  "common_valid_intervals": [
    {
      "start_unix_ms": 1789286400007,
      "end_unix_ms": 1789286400028,
      "duration_ms": 21
    }
  ],
  "longest_common_duration_ms": 21,
  "qualified": true
}
```

服务先按单测点规则求出每个测点的闭合有效区间，再按测点顺序对全部区间求交（相接区间照常合并），得到全部公共有效区间；`qualified` 仅由最长公共区间决定：

```text
longest_common_duration_ms >= minimum_duration_seconds × 1000
```

非法请求返回 HTTP 422，错误位于 `error.fields`，每项提供 `location`、`code`、`message` 和可用的 `context`；校验失败时不会返回任何判定结果。联合请求的嵌套错误会定位到具体测点与读数字段，例如 `["body", "points", 1, "readings", 0, "concentration_ppm"]`。

## 领域规则

- 时间戳必须是以 `Z` 结尾、精确到毫秒的 ISO 8601 UTC 字符串：`YYYY-MM-DDTHH:mm:ss.sssZ`。
- 读数至少两条，时间戳严格递增，首末跨度不得短于最低持续时间。
- 浓度和阈值必须为非负有限数。
- 最低持续秒数必须为大于零的有限数，且最多三位小数。
- 保守复核的测量误差上限必须为非负有限数，且最多三位小数；判定前从每条浓度扣除并下限截为零。
- 相邻读数之间按直线插值，浓度等于阈值属于有效。
- 插值穿越点先换算为 Unix 毫秒值，再四舍五入；半毫秒向远离零方向取整。
- 原始采样点直接使用其毫秒整数时间。
- 区间持续毫秒数为 `end_unix_ms - start_unix_ms`。
- 区间首尾闭合；相接区间合并，分离区间不可相加。
- 联合复核中每个测点序列遵守以上全部规则；测点编号非空且请求内唯一，测点数为二至十个，各序列首末时间戳必须一致。

## 本地运行（Docker Compose）

默认宿主机端口为 `8000`：

```bash
docker compose up --build
```

通过 `API_PORT` 覆盖宿主机端口：

```bash
API_PORT=9090 docker compose up --build
```

健康检查：

```bash
curl http://localhost:${API_PORT:-8000}/health
```

## 测试

```bash
python3.12 -m pip install -r requirements-dev.txt
pytest
```

## 项目结构

```text
app/
  domain.py      # Pydantic 领域契约与字段级校验（单测点、保守与联合请求）
  calculator.py  # 不依赖 Web 的插值、区间合并、区间求交、误差扣减与判定计算器
  schemas.py     # API 响应模型
  routes.py      # /verify、/verify-conservative 与 /verify-joint 路由
  errors.py      # 路由层校验错误映射
  main.py        # FastAPI 应用入口
tests/           # 领域、计算器与 API 测试
```
