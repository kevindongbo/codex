# 官方规则核验与数据准入

检索日期：2026-10-26，Asia/Shanghai。下表为官方公开资料的简要核验记录，不是已经导入系统的配置。原始网页、搜索缓存、截图和签名媒体URL不提交仓库；只保存来源页、结论、适用范围及待核验项。Firecrawl已配置但拒绝该站点，随后使用网页检索和直接打开官方页面；未登录卖家后台，未抓取密钥。

## 1. 来源台账

### S-US-01：平台佣金与摄像头收费组

[TikTok Shop Referral Fees in 2024 by Category](https://seller-us.tiktok.com/university/essay?knowledge_id=5988482086864682)，页面显示2026-10-08更新。公开表列出 Phones & Electronics / Cameras & Photography 为6%；公式为费率乘“客户支付+平台折扣−税”，且说明基数包括买家支付的运费。**适用：美国已匹配该收费组、无特殊优惠的交易**。不能把6%当作所有国家或所有电子类目的永久常量。促销、退款和具体SKU类目须另匹配版本。

### S-US-02：官方可见安防类目路径

[Buy with Confidence](https://seller-us.tiktok.com/university/essay?knowledge_id=4308706540554036) 的类目列表可见 `Phones & Electronics → Cameras & Photography → Security Cameras & Systems`。该页能证明名称路径，**不能证明用户店铺已获准销售，也不提供可直接使用的类目ID**。可视门铃及监控子型仍需实际店铺类目树核验；不得把该保障计划的参加名单当成完整发布分类API。

### S-US-03：Standard Delivery

[What is TikTok Shipping - Standard Delivery](https://seller-us.tiktok.com/university/essay?knowledge_id=987788883576589)，页面显示2026-10-13更新。面单由平台提供，物流公司由平台匹配；按实重与体积重较大者计费，页面示例使用立方英寸除139。承运商复测可能调整费用；还存在尺寸、重量及服务附加费。适用Standard的公式不得复制给其他服务；完整价表、分区、进位、附加费和店铺资格须取得后才能自动报价。

### S-US-04：旺季日期

[TikTok Shipping Peak Season Shipping Rate](https://seller-us.tiktok.com/university/essay?knowledge_id=4797361814980370)，页面显示2026-09-26更新。2026-10-05至2027-01-17太平洋时间存在Standard旺季调整，并按LIVE／非LIVE、区间和重量细分；CBT另有规则。**2026-10-26处于该窗口**，不能只使用常规价或中国日期判断边界。计划必须支持规则日期区间及当地时区。

### S-US-05：FBT

[FBT Rate Card & Frequently Asked Questions](https://seller-us.tiktok.com/university/essay?knowledge_id=3507056320268087)。文中2026-05-01起的履约规则：实重≤2lb且体积≤332in³按实重，否则比较实重与按166除数计算的体积重；价表还按服务和生效日期区分。包含拣包／尾程的履约费、仓储及其他费用不能重复记账。完整金额多为图片，本轮未转录成生产费率，也不将入仓Hub规则混同末端履约规则。

### S-US-06：卖家自发货

[Seller Shipping: Overview and Services](https://seller-us.tiktok.com/university/essay?knowledge_id=8308896260065025)，页面显示2026-08-12更新。适用于美国当地仓自发货，物流由卖家安排，有有效追踪及服务时效要求。面向买家的“Free Economy”不代表商家物流成本为0。具体承运商合同价需作为商家报价来源，不冒充TikTok统一官方价。

### S-US-07：销售税

[US Sales Tax FAQ](https://seller-us.tiktok.com/university/essay?knowledge_id=77147478607658)。TikTok作为marketplace facilitator按适用规则代收代缴销售税，通常结账时加收，商品售价不含该税；税率与商品及地址有关。平台代收税不算商家销售收入，也不能再次作为相同金额的经营费用扣减。此FAQ不替代商家其他税务义务或店铺税务配置。

### S-US-08：电子产品与安防边界

[Electronic Products Requirements](https://seller-us.tiktok.com/university/essay?knowledge_id=1418345612003114) 与 [Prohibited Products Policy](https://seller-us.tiktok.com/university/essay?knowledge_id=1399532709988097)。电子产品需满足适用品类资质；普通公开用途安防设备与隐蔽、伪装或用于未授权监控的设备不能混同。利润类目不能被界面标为“已获准上架”，资质材料和带电运输适配需独立核验。本期只规划正常安防、监控、门铃。

### S-MX-01：平台佣金与每件费用

[Tarifa de Comisión de la Plataforma y Tarifa por artículo vendido](https://seller-mx.tiktok.com/university/essay?knowledge_id=309514093152016)，页面显示2026-07-02更新。列明含适用税的6%平台佣金；自2026-07-06墨西哥时间起增加每件MXN6的售出费用；示例佣金基数包括买家运费。新商优惠有期限／资格，且不免每件费。**同SKU多数量、部分退款、固定费退还边界须用官方明细或结算样例补核**，不得只按“每订单6比索”实现。

### S-MX-02：SFP运费计划

[Shipping Fee Program (SFP)](https://seller-mx.tiktok.com/university/essay?knowledge_id=4397124533274384&lang=en)，页面显示2026-09-22更新。页面列有8%的服务费，2026-06-22起每件封顶MXN40，并将服务费与物流／补贴分开说明。**SFP不是美国FBT**。实际入会、计费基数、补贴资格、重复数量和退款边界须与店铺配置一致；不因为页面称默认计划就假设每家店均参加，未确认补贴不得自动冲减成本。

### S-MX-03：Standard当地物流

[Servicio estándar: guía de tarifas de envío](https://seller-mx.tiktok.com/university/essay?knowledge_id=113845273118465&lang=es-419)，页面显示2026-08-28更新，包含2026-06-22起价表。按起运／收货区域和计费重量收费；描述取卖家及承运商申报／测量的实重、体积重最大值，注明含IVA且不接受超过30kg包裹。完整区域表和重量公式以图片／链接形式给出，**本轮未核实除数、全部档位与进位规则**，不能擅填5000或6000。

### S-MX-04：发货能力限制

[Compare Shipping Solutions](https://seller-mx.tiktok.com/university/essay?knowledge_id=4012989939222289)，页面显示2026-03-11更新。平台发货和卖家发货不同；卖家自发货只向部分卖家开放，平台模式下承运商由平台匹配。文中发货方式是店铺级设置，变更仅影响之后订单。本期需按店铺资格控制选项，不能让用户在模拟器中误认为订单可以任意混用尚未开通的服务。墨西哥平台仓独立资格／价表本轮未确认。

### S-MX-05：税款代扣

[Seller Withholding Taxes](https://seller-mx.tiktok.com/university/essay?knowledge_id=5000424638367505&lang=en)，页面显示2026-03-26更新。IVA／ISR代扣受RFC状态、登记类型与产品税务属性影响，部分地区另有规则。公开表格与示例对ISR基数的表述存在需要进一步核验之处；本需求包**不据此发布统一税率或基数**。必须区分商品价内IVA、平台服务费含税和平台代扣税；收款减少不等于相同金额都为不可抵扣费用。

### S-MX-06：电子产品资格

[Política de Productos Restringidos de TikTok Shop](https://seller-mx.tiktok.com/university/essay?knowledge_id=8357469202958081&default_language=es-419)。电气／电子产品有相应资料与批准要求。该政策不提供完整安防类目的末级ID或店铺开通状态；不得直接复制US的类目ID、资质或运费到MX。

## 2. 冲突与不能照搬的规则

| 问题 | 本期处理 |
| --- | --- |
| 美国不同概览出现166、Standard示例139、FBT又有小件实重例外 | 以具体服务、有效日期和官方规则卡为键；概览不覆盖专用规则。无法消解的版本拒绝发布，不使用全美统一除数 |
| 价表为图片或依赖后台Shipping Calculator | 数据人员核对原图与店铺报价，二人复核至少典型和边界样本；本期文档不填整张未读价表 |
| MX运费按地区而非一个全国价 | 必须取得地区映射、起讫信息与服务版本；缺目的地只能给带范围的情景报价，不能输出伪精确利润 |
| 消费者包邮与商家实际支出不同 | 买家运费、平台代收、商家承担、运费补贴与计划服务费分行；防止同笔费用重复扣减或补贴重复相加 |
| 墨西哥SFP与平台仓英文缩写容易混淆 | 字段、文案、费项明确区分；SFP=运费计划，FBT=特定平台仓履约服务 |
| 新商0佣金等活动 | 单独优惠规则，必须有店铺资格、开始/截止/上限；过期回标准规则，不默认开关为开 |
| 税务主体未知 | 仅输出有范围说明的经营测算；税务／回款字段标缺失，不能称完整到手利润 |

## 3. 规则数据准入（G-RULE）

每份版本至少记录：market、seller_program、service_code、fee_group、currency、单位、来源标题及URL、来源更新时间、verified_at、effective_from/to、时区、完整公式及边界、适用资格、是否含税、计费粒度（件／SKU／包裹／订单）、rounding_policy、最大尺寸重量、区域映射版本、审核人、内容hash及测试样本。

数据状态：`draft → reviewed → published → superseded`；有冲突标为`blocked`。只有published且在试算日期有效、与店铺条件匹配的版本能作为“官方自动规则”。后端无匹配返回缺失原因，不回退到其他国家、其他服务、最新但尚未生效的版本或0费用。

人工录入允许“商家确认报价／人工费率”，必须有金额、币种、适用范围、确认人、日期和备注，界面显著标为人工；它不改写官方规则，不用于填补未知的销售资格，也不自动传播至所有商品。运行时不依赖即时抓网页或付费模型计算费用。

## 4. 实施前必须取得的数据

1. 实际US/MX店铺的销售主体类型、发货项目和已开通物流；不收集完整税号到公开文档。
2. 安防摄像头、监控、门铃的官方末级ID、祖先路径、有效收费组和具体产品资格；US已见路径只是起点，MX需单独取树。
3. US Standard／CBT／FBT分别的有效价表、进位、区划、重量与尺寸附加费、旺季／LIVE及活动条件；不一定每店都支持全部模式。
4. MX标准面单价表、地区映射、体积重公式与单位；自发货资格及合同报价；平台仓是否已向该店开放。
5. MX售出固定费、SFP、退款边界和税务资料的结算样例；带电产品的实际渠道适用限制。

以上属于上线前外部数据核验门禁，不改变用户已确认的功能方向，也不允许用虚构种子数据提前宣称已覆盖两国。
