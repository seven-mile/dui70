# DirectUI (dui70.dll / duser.dll) 逆向教程系列

24 篇教程,写给「想在自己应用里用 DirectUI 的 C++ 开发者」。全部结论基于
dui70.dll 26200 x64 的 PDB 符号、全量反汇编(`.local/build/dui70-full-disasm.txt`)
与 149 份真实系统 UIFILE 语料(`docs/duixml-corpus/`),每条结论按证据分级标注。

> **证据分级**(全系列统一):
> - **【实锤】** —— 反汇编/导入表/运行时观测直接证明
> - **【强推】** —— 有推断链的多方证据,未到最后一步
> - **【猜想】** —— 合理假设,文中写明验证路径
>
> 不知道的写「不知道」并进篇末「未知问题清单」——这是系列纪律。

## 阅读顺序

### 第一部分:解析——duixml 从文本到元素树(01-03)

| # | 篇目 | 一句话 |
|---|---|---|
| [01](01-duixmlparser-xml-to-element-tree.md) | DUIXmlParser 从 XML 到元素树 | 154 成员职责地图;两级标签查找(私有表→全局二分) |
| [02](02-value-type-system.md) | Value 类型系统 | 110 方法完整类型表;`<macro>`/`<bind>` 机制;rp 单位 |
| [03](03-host-registered-tags.md) | 宿主注册标签 | 154 个语料标签无对应类的开放 schema;`attach="{Dll!Func}"` |

### 第二部分:无障碍——UIA 三部曲(04-06)

| # | 篇目 | 一句话 |
|---|---|---|
| [04](04-uia-accessible-bridge.md) | UIA 桥 | WM_GETOBJECT→UiaOnGetObject;acc* 属性族;双轨 MSAA |
| [05](05-uia-pattern-providers.md) | 13 个 PatternProvider | ICF 折叠的平凡 stub;MSVC 模板参数改写规则 |
| [06](06-uia-invoke-helper-cross-thread.md) | InvokeHelper 跨线程通道 | 隐藏窗口;`DUI_UIA_InvokeHelperMsg`;含可运行探针 `probe-uia-invokehelper.ps1` |

### 第三部分:文本——两代引擎(07-08)

| # | 篇目 | 一句话 |
|---|---|---|
| [07](07-richtext-and-the-dwrite-bridge.md) | RichText 与 DWrite 桥 | 三阶段生命周期;Run 系统;LoadLibraryW 手动加载 dwrite |
| [08](08-ptext-and-the-old-text-era.md) | PText 与旧文本时代 | 78/78 全在样式表;GDI 管线指令级解码;Value 类型枚举实锤 |

### 第四部分:样式与主题(09-12)

| # | 篇目 | 一句话 |
|---|---|---|
| [09](09-stylesheet-three-layers.md) | 三层皮肤 | `<if>` 伪类 3865 处;ImmersiveBase 继承链 |
| [10](10-dark-mode-switch-chain.md) | 明暗切换全链路 | ImmersiveColorSet→FlushThemeHandles→样式表重载,逐步附 RVA |
| [11](11-xfamily-xbaby.md) | X* 家族 | XHost/XElement/XProvider/XBaby;comdlg32 假说否证 |
| [12](12-dpi-scaling-rp-units.md) | DPI 与缩放 | rp 解析期烘焙;GetScaleFactor 三路分发 |

### 第五部分:布局与导航(13-15)

| # | 篇目 | 一句话 |
|---|---|---|
| [13](13-layout-landscape.md) | 九种布局的真实用法分布 | borderlayout 65% 统治;`.rdata` 分发表字节级实锤 |
| [14](14-layout-protocol.md) | Layout 虚协议 | vtable 9 槽解码;生命周期五幕 |
| [15](15-keyboard-navigation.md) | 键盘导航 | NavScoring 打分公式指令级还原;分布式 GetAdjacent |

### 第六部分:运行时骨架(16-18)

| # | 篇目 | 一句话 |
|---|---|---|
| [16](16-startup-and-threading.md) | 启动序列与线程模型 | InitProcessPriv/InitThread;defer 事务(cookie 0xABCDEF42) |
| [17](17-events.md) | 事件系统 | 三级流水线;Event 布局构造侧实锤;无中心翻译表 |
| [18](18-properties-and-lifecycle.md) | 属性系统与生命周期 | specified value 栈;Value 引用计数编码;Destroy vs Detach |

### 第七部分:视口与 HWND 互操作(19-21)

| # | 篇目 | 一句话 |
|---|---|---|
| [19](19-viewer-family.md) | Viewer 家族分工 | Viewer→ScrollViewer→TouchScrollViewer;DirectManipulation 引擎 |
| [20](20-scroll-physics.md) | 滚动的物理层 | 滚轮到像素位移完整因果链;duser gadget 树 |
| [21](21-hwnd-interop.md) | HWND 互操作三层楼 | NativeHWNDHost/HWNDElement/HWNDHost;CC* 寄生模式 |

### 第八部分:按钮与选择(22-24)

| # | 篇目 | 一句话 |
|---|---|---|
| [22](22-buttons-three-generations.md) | 按钮编年史 | Button→CC*→Touch* 三代平行共存;AutoButton 之谜 |
| [23](23-selector-and-itemlist.md) | Selector 与列表选择 | 点击选择活在 SelectorNoDefault;ItemList 虚拟化 |
| [24](24-glyph-buttons-little-graphics.md) | Glyph 们 | 纯样式挂钩;勾=字体字形非位图 |

## 系列背景

- **语料库**:149 份 UIFILE(64 个系统 DLL),见 `docs/duixml-corpus/`(README 含统计)
- **任务大纲**:`.local/audit/duixml-tutorials-outline.md`(组件族 A-L)、
  `.local/audit/ui-mental-model-outline.md`(横切面 §1-§12)——注意 outline 的早期
  数字与教程实测有出入时,以教程为准(教程经过独立 QA 复核,见下)
- **质量流程**:每篇由包作者交付→Lead 抽验硬声明→独立 QA(`.local/audit/tutorial-qa-report.md`,
  320 条复核)→交叉复验(UIA 三篇由非作者复验 18 条)→Lead 终审定稿
- **公共上下文**:`.local/audit/COMMON-CONTEXT.md`(写作规范/证据分级/工具链)
- 本系列不修改 `DirectUI/`(代码还原)、`tools/dui-pipeline/`(流水线)、`pinned/`(冻结输入)
