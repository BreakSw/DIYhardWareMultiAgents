# 首批硬件知识采集设计

## 1. 目标

为 RAG 准备一批可审查的当前硬件知识。首批数据强调字段完整、来源可追踪和价格可验证，不追求伪全量。

本地脚本只负责编排托管平台 API，不直接请求厂商或电商目标网页。目标页面统一交给 Apify、Bright Data、Zyte 或 Firecrawl 获取，避免在项目中维护代理池、验证码处理、浏览器指纹和站点选择器。

首批覆盖：

- CPU
- GPU
- 主板
- 内存
- 固态硬盘
- 电源
- 散热器
- 机箱

每个类别最多接受 3 条记录，共最多 24 条。产品型号由搜索和市场证据动态发现，源码不维护固定型号名单。

## 2. 平台职责

### SerpAPI

- 使用美国区域和美元价格搜索当前商品。
- 获取候选型号、商品链接、商家、价格、库存线索和搜索排名。
- 每个类别只执行有限次数的发现请求。

### Firecrawl

- 将厂商官方产品页转换为 Markdown 和结构化内容。
- 保存正文、页面标题、来源 URL 和抓取时间。
- 主要用于规格页和文档型页面，不作为最终价格来源。

### Zyte

- 对商品页执行 `product` 自动提取。
- 获取产品名、MPN、SKU、USD 价格、库存和附加属性。
- 必要时使用自定义属性 schema 提取硬件类别字段。

### Bright Data

- 用商品 Scraper 获取第二组零售价格和库存证据。
- 优先使用配置的商品 Scraper `dataset_id`；没有商品 Scraper 时使用配置的 Web Unlocker zone 获取零售页面。
- 如果 Token 有效但账户既没有 `dataset_id`/Collector，也没有可用 Web Unlocker zone，平台状态记录为 `not_ready`，该批次继续运行，不能声称 Bright Data 已参与价格验证。

### Apify

- 使用公开 Web Scraper Actor 批量抓取普通 HTTP 无法稳定获取的产品页。
- 作为浏览器渲染和页面正文回退，不负责决定产品是否主流。
- 保存 Actor run ID 和 dataset item 来源，便于追踪费用和失败。

### ECB

- 获取最近工作日的 EUR/USD 与 EUR/CNY 参考汇率。
- 计算 `USD/CNY = CNY/EUR ÷ USD/EUR`。
- 保存汇率发布日期、抓取时间和数据年龄。

## 2.1 网络访问边界

脚本允许直接访问：

- SerpAPI 官方 API。
- Apify、Bright Data、Zyte、Firecrawl 官方 API。
- ECB 官方汇率接口。

脚本禁止直接访问：

- 厂商产品页面。
- 电商商品页面。
- 搜索结果中的任意目标站点。

平台返回的页面正文、结构化商品和价格证据可以写入原始数据目录。脚本不得包含针对目标站点的 CSS 选择器、Cookie、代理地址、浏览器自动化或反验证码代码。

## 3. 主流产品判定

候选产品通过以下动态信号排序：

- 官方产品页仍有效。
- 美国市场存在新品在售报价。
- SerpAPI 搜索排名。
- 独立商家数量。
- 商品结果中的评价数量。
- 报价更新时间。

排序只使用本批次返回的市场信号，不在代码中写入具体品牌、系列或型号。

## 4. 完整字段

### 通用字段

- `category`
- `brand`
- `model`
- `mpn`
- `market`
- `specs`
- `price`
- `exchange_rate`
- `sources`
- `fetched_at`
- `content_hash`
- `quality`

### CPU 必填规格

- socket
- cores
- threads
- base_clock
- boost_clock
- tdp_w
- memory_types
- pcie_version

### GPU 必填规格

- chipset
- vram_gb
- memory_type
- tdp_w
- length_mm
- power_connectors
- recommended_psu_w

### 主板必填规格

- socket
- chipset
- form_factor
- memory_type
- memory_slots
- max_memory_gb
- pcie_slots
- m2_slots

### 内存必填规格

- memory_type
- total_capacity_gb
- module_count
- speed_mt_s
- cas_latency
- voltage

### 固态硬盘必填规格

- capacity_gb
- form_factor
- interface
- protocol
- sequential_read_mb_s
- sequential_write_mb_s
- endurance_tbw

### 电源必填规格

- wattage_w
- efficiency_rating
- form_factor
- atx_version
- modular_type
- pcie_connectors

### 散热器必填规格

- cooler_type
- supported_sockets
- height_mm 或 radiator_size_mm
- fan_count
- rated_tdp_w 或由厂商明确给出的适用处理器范围

### 机箱必填规格

- supported_motherboard_form_factors
- max_gpu_length_mm
- max_cooler_height_mm
- supported_radiators
- psu_form_factor
- drive_bays

任何类别缺少必填规格时进入 `rejected`，不会使用大模型推测缺失值。

## 5. 价格规则

- 只接受新品报价。
- 原始货币必须为 USD。
- 每条报价保留商家、URL、价格、库存和抓取时间。
- 至少存在一个有效 USD 报价才能进入 accepted。
- 优先要求来自两个独立平台或商家的报价。
- 参考美元价取有效报价中位数，同时保存最低价与最高价。
- 人民币价格只作为 ECB 汇率换算参考，不冒充中国市场成交价。

## 6. 数据目录

```text
backend/data/knowledge/hardware/
├── raw/<batch_id>/<provider>/
├── normalized/<batch_id>/hardware.jsonl
├── rejected/<batch_id>/hardware.jsonl
└── manifests/<batch_id>.json
```

`raw` 响应在写盘前删除 API Key、Authorization、Cookie 和敏感请求头。

## 7. 脚本接口

脚本位置：

```text
backend/scripts/crawl_hardware_knowledge.py
```

命令：

```powershell
python scripts/crawl_hardware_knowledge.py --per-category 3 --market US
```

支持：

- `--categories`：限制类别。
- `--per-category`：每类接受数量上限。
- `--market`：市场，首批为 US。
- `--providers`：选择已配置平台。
- `--resume-batch`：恢复未完成批次。
- `--dry-run`：只检查配置和计划，不调用付费 API。

脚本通过 provider 协议调用各平台。平台适配器相互独立，后续可替换，不在采集逻辑中散布平台判断。

## 8. 成本和失败策略

- 默认串行、小批量运行，避免意外并发扣费。
- 单个外部请求最长等待 15 秒。
- 对 429 和临时 5xx 最多重试两次，并使用退避。
- 单个平台失败不会让其他平台结果消失。
- 规格字段不完整、价格无证据、来源不可靠或型号无法归一化时进入 rejected。
- 所有失败在 manifest 中记录安全错误码，不记录完整异常 URL 中的密钥。

## 9. 验收

- 八个类别均产生 accepted 或明确的 rejected 原因。
- accepted 记录所有类别必填字段完整。
- accepted 记录至少有一条 USD 价格证据。
- 每条记录有官方或可识别产品来源。
- 汇率记录包含 ECB 日期和 USD/CNY。
- 所有平台在 manifest 中有 `completed`、`failed` 或 `not_ready` 状态。
- 原始数据和 manifest 中不出现 API Key。
- 网络日志证明所有目标网页均由托管抓取平台获取，本地脚本没有直接请求目标站点。
- 本批次不会自动写入 Qdrant，用户审查后再进入分片与索引阶段。
