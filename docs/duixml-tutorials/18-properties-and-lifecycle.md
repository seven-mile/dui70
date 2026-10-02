# 教程 18:属性系统与生命周期 —— Value/PropertyInfo/引用计数

> 系列教程第 18 篇。前置:`16-startup-and-threading.md`(defer 事务)、`17-events.md`(OnPropertyChanging 回调已露面)。
> 证据分级:**【实锤】** / **【强推】**(附推断链)/ **【猜想】**(待验证)。
> 主题:Element 的另一半灵魂——属性怎么存、怎么取、怎么变,以及万物如何生灭。

---

## 0. 全景:三件套

```
PropertyInfo  —— 属性的"身份证":名字、类型能力、flags(每个属性一份 .rdata 常量)
Value         —— 属性的值:带类型标签的 variant + 引用计数(每属性每元素一份运行时对象)
Element       —— 持有者:本地值表 + 监听器数组 + 树关系 + 引用计数
```

心智模型:**属性系统 = "specified value 栈 + 样式合成 + 依赖失效"三件套**。与 CSS 不可类比——没有选择器引擎(选择在 StyleSheet 层做,`09-stylesheet-three-layers.md` 主题);与 WPF 也不可类比——没有 DependencyProperty 全局注册表,**PropertyInfo 就是编译期固化的反射记录**。

---

## 1. PropertyInfo:编译期反射【实锤】

### 1.1 结构布局(本次新还原)

每个属性一个静态工厂(`Element::AlphaProp()` 等),返回指向 .rdata 常量块的指针。五个代表属性的字节级对照(Alpha/Content/Width/MouseWithin/Enabled):

```
PropertyInfo {
  +0x00  PCWSTR      name          // "Alpha" 等,UTF-16 常量
  +0x08  DWORD flags_lo            // 0x26 / 0x06 / 0x11 / 0x2e ...
  +0x0c  DWORD flags_hi            // 0x00000000 / 0x00000001 / 0x00020000 ...
  +0x10  Cap*        cap           // 类型能力数组(见下)
  +0x18  ?
  +0x20  fnptr       (类型相关,疑似 Value 构造/解析辅助)
  +0x28  fnptr       (类型相关)
}
```

**cap 数组**:8 字节一项 `{DWORD type, DWORD -1}`,按 ValueType 枚举值排列。实测 Alpha 的 cap 串是 `1,-1, 2,-1, 0xc,-1, 0xe,-1, 5,-1`(多个候选类型:Bool=2? Int=3? —— 对照 UITest 的 ValueType 枚举,Alpha 允许 Int/Float 等;MouseWithin cap 首项 2、Enabled cap 首项 2)。**cap 是"该属性接受哪些值类型"的白名单数组**,UITest.cpp:176 `to_string(prop->cap->type)` 打印的正是首元素。【实锤:字节dump + UITest 用法交叉;各项与 ValueType 枚举的精确对应未逐一核对,标注:cap 首项 = 主类型】{平铺对照数据在 `.local/build/ui-mental-model/propinfo_table.py` 输出}

flags_hi 的 0x00020000 位(Content/Alpha/Enabled 有、Width/MouseWithin 无)与"可继承/可动画/可序列化"哪个对上——**未定**,见 §7 未知。

### 1.2 属性表从哪来:ClassInfo 注册 + 运行时 dump

`IClassInfo::EnumPropertyInfo(i)` / `GetPICount()` 是公开反射入口(UITest.cpp:153-188 `DumpClassInfo` 用它们遍历每类全部属性,连 enum_value_map 的 (str,int) 对都打印了)。元素层级约 70 个 *Prop 静态工厂(Element 类 71 个,符号表计数),基类属性被子类继承(注册表按基类链合成)。

使用者最常见的操作是比较 PropertyInfo 指针:

```cpp
// UITest.cpp:635-638 —— 属性变更监听里按"是哪个属性"分发
static const PropertyInfo *mouseWithinPI = Element::MouseWithinProp();
if (prop == mouseWithinPI) { ... }        // 指针比较,与 UID 同构
```

【实锤,可运行样本】PropertyInfo 与 UID(`17-events.md`)是同一设计哲学:**身份 = 常量地址**。

### 1.3 读取链:GetValue 的分层

`Element::GetValue` 有两个重载(RVA 0x24170 与 0x24AF0,签名差异在参数);内层链:

```
GetValue(prop, idx, cache)
  └→ GetRawValue(0x249E0)               // 拿本地(specified)值
       └→ _GetSpecifiedValue(0xFF40)    // 二分查本地值表(见 §1.4)
       └→ _GetComputedValue(0xECA0)     // 样式/继承合成(未完整还原)
```

_GetSpecifiedValue 反汇编可见**二分查找**(本地值表按 PropertyInfo 指针排序,`cmpq/jb/ja` 经典循环,行 0x18000FFC6 起):本地值不是哈希表而是**有序指针数组**。查不到 → 走 _GetComputedValue 合成(样式表查询 + 继承 + 类默认值)。

**合成优先级**(inline > sheet > inherited > default?)——顺序未验证,保持【强推】;验证路径见 §7。

### 1.4 SetValue:写路径与 OnPropertyChanging 否决

`Element::SetValue` → `_SetValue`(0x22C20)是所有属性写(含 XML 解析期)的统一漏斗。反汇编还原的关键步骤:

```
1.  vtable+0x118 虚调用                    // OnPropertyChanging 通知(true=放行)
    ↓ 返回 0 → 拒绝,终止
2.  二分定位本地值表槽位
3.  新旧 Value 引用计数交接(AddRef 新 / Release 旧)
4.  登记到 DeferCycle(若在事务中)或立即失效
5.  触发 OnListenedPropertyChanged 监听回调
```

UITest 的属性拦截实验(UITest.cpp:633-656)同时用了两层:lambda 版 OnPropertyChanging 拦截 + `prop == alphaPI` 比较——与 §1.2 的指纹比较惯用法一致。

**动画短路**:`SetAnimation` 之后的 `SetAlpha` 走特殊视觉路径(UITest 动画实验证明视觉在 DUser 插值而属性只变更一次)——机制归属性系统与动画层交界,详见 animation-expressiveness.md,此处只强调:**SetValue 对动画属性有旁路**,不重复触发每帧属性变更。

---

## 2. Value:带类型标签的 variant【实锤】

### 2.1 类型字典

ValueType 枚举(UITest.cpp:106-151 完整还原,22 个值):Unavailable/Unset/Null/Int/Bool/Element/Ellist/String/Point/Size/Rect/Color/Layout/Graphic/Sheet/Expr/Atom/Cursor/Float/DblList + 保留。

工厂家族(110 个符号,value_members.txt):**Create**Atom/Bool×3/Color×3/Cursor×2/DFCFill/DTBFill/DoubleList×2/ElementList/ElementRef/ElementScaledValue/EncodedString/Expression/Fill/Float/Graphic×7/Int/Layout/Point/Rect/ScaledValue/Size/String/StringRP/StyleSheet/ValueList×2 —— 25+ 种构造路径。

**类型化单例**(免分配快路径):GetBoolTrue/False、GetIntZero/MinusOne、GetFloatOne/Zero、GetPointZero、GetRectZero、GetNull、GetAtomZero、GetLayoutNull、GetElListNull、GetElementNull、GetExprNull、GetSheetNull、GetDblListEmpty、GetCursorNull、GetColorTrans。——**常见值不分配**,AddRef 即可。这就是为什么 AddRef/Release 的热路径做得极薄(§2.2)。

### 2.2 引用计数的真实指令【实锤,本次新还原】

Value 的计数不是对象头部的普通 int,而是**首个 DWORD 的低位复用**:

```
Value::AddRef (0x4ECE0):
  eax = [rcx] & 0xFFFFFF80        // 计数在高位 25 位,步长 0x80
  if (eax == 0xFFFFFF80) return   // "永久/静态"标记,不增
  lock addl $0x80, (rcx)

Value::Release (0x24600):
  eax = [rcx] & 0xFFFFFF80
  if (eax == 0xFFFFFF80) return   // 永久对象不减
  lock xaddl $-0x80 → 计数归零 → _ZeroRelease(0x24640) 真析构
```

**计数步长 0x80、低位 7 位是类型/标志位**【实锤,指令级】。低位 7 位里能看到的语义:最高位 bit7(0x80)是"永久对象"标记(命中则 AddRef/Release 全部短路——单例就是它);GetValue 里还有 `andl $0x3F` 的检查(`17-events.md` 引用过的 `shll $0x1a` 类型标签提取也在同一区域)。

**RefcountBase**(0x66720 AddRef / 0x533C0 Release)是干净版:计数在 +0x08,`lock xaddl` 步长 1,归零调 vtable[1] 析构(vector deleting dtor)+ 释放。Element 本体的 AddRef/Release(RVA 0x7ADA0)**是纯 `retq`**——Element 不用引用计数管理生命周期!树所有权才是 Element 的生命周期(§4)。这是对`16-startup-and-threading.md` §3 所有权模型的关键补强。【实锤】

### 2.3 使用者模式:Get/Release 配对

```cpp
// UITest.cpp:574-579(GetContentString 精简)
Value *v;
elem->GetValue(Element::ContentProp(), &v);   // 引用转移给调用者
// ... v->GetString() 使用 ...
v->Release();                                  // 用完必还
```

XML 里的一切属性最终都走 SetValue:高频属性(activityv/accessible/content/background/margin/padding/layout/layoutpos/sheet/class/id...)在解析期被转换;`<style>` 块内的同名属性走样式路径(`09-stylesheet-three-layers.md`)。

---

## 3. 监听器数组:AddListener 的分配器【实锤,本次新还原】

`17-events.md` 遗留的监听器数组结构,这里补完(AddListener@0x1E8E0):

```
Element+0x40 = ListenerBlock*:
  +0x00  迭代器/快照头(OnEvent 遍历时被临时替换)
  +0x08  count
  +0x0c  capacity
  +0x10  IElementListener* 槽数组(count 项)
```

AddListener 流程:无块 → 分配(容量 count+0x17,经 0x18003AF84 分配器——RefcountBase 构造族);有块 → **只写槽不加容量**(扩容走完整重分配);随后调用监听器 vtable+0x10(OnListenerAttach)。

RemoveListener(0x1E1C0):**槽位置换为哑元 vtable(0x180103438),count 不减**——保证存活监听器索引稳定,遍历安全(快照协议见`17-events.md` §4.3)。真正收缩在元素析构时的批量路径。

**使用者含义**:AddListener 是 O(1) 追加;RemoveListener 后数组只增不减(直至元素销毁)——高频挂摘场景(提示条之类)要意识到槽位泄漏倾向。【实锤,指令级;长期泄漏的量化是【猜想】】

---

## 4. 生命周期:Destroy vs Detach vs 延迟销毁

### 4.1 三个词的真实语义【实锤,反汇编】

**Detach(0x2FB60)——"摘下"**:

```
1. 从父元素兄弟链/子链中移除(维护 0x28/0x2c 索引)
2. 本地值表槽位清零(0x28/0x2c 置 -1 = "无父"标记)
3. DeferCycle 登记(_VoidPCNotifyTree:结构变更通知)
4. 元素对象本身不动——引用计数不变,属性不释放
```

**Destroy(0x5FE20)——"处决"**:

```
1. vtable+0x140 虚调用(OnDestroy 类通知)
2. 若有 gadget 句柄(+0x8):构造 EventMsg{cbSize=0x10, msg=0x83FF}
   → DUserPostEvent                  ← 延迟销毁消息,交给 duser 排队
3. (后续:子树销毁、属性 Value 逐个 Release、监听器 OnListenerDetach...)
```

**DestroyAll(0x67E30)**:批量版本。

0x83FF 延迟销毁(duser-deep-dive §1.3)的意义:**销毁也有事务语义**——Destroy 调用返回时元素还"在"(duser 队列里),本帧渲染/事件循环结束才真回收。这防止了"事件处理中销毁自己"的经典 use-after-free。

### 4.2 所有权心智模型

> **树持有子,属性持有 Value,parser 持有样式表与模板。**
> Element 不引用计数(AddRef 是空操作);Element 的生死由树决定——Detach 摘下但活着(可以再挂回去),Destroy 才是死刑(且是缓期执行)。

这是对 outline §12 【强推】的升级:Element::AddRef 纯 retq【实锤】消除了"Element 也是 RefcountBase"的可能误读。Value 永远归属性所有,Detach 不碰 Value;监听器归元素所有,元素死时 OnListenerDetach 通知。

defer 事务(`16-startup-and-threading.md` §3)与生命周期的关系:构建期创建的元素在 EndDefer 前对用户不可见;若事务中 Destroy,登记进同一 DeferCycle,提交时统一结算——**事务性构建的镜像就是事务性销毁**。【强推:DeferCycle 登记表两端写入;提交侧统一结算的完整验证待做】

---

## 5. 常见坑

1. **Get 出来的 Value 必须 Release**(§2.3)——忘了就泄漏,多了就崩溃。单例(GetBoolTrue 等)虽然 AddRef/Release 短路,但**不要依赖这个偷懒**:普通值不短路。
2. **OnPropertyChanging 返回 false 能否决用户的 SetValue**,但框架内部的属性写(布局输出 width/height)不给你否决机会(内部写不走通知路径的分支存在——`_SetValue` 有无通知快速路径)。
3. **Detach ≠ Delete**:Detach 后的元素如果没有人再 Attach 或 Destroy,就是纯泄漏(树不再持有它,引用计数又不管 Element)。
4. **Destroy 是异步的**:Destroy 之后同帧还能收到该元素的事件(队列里的 0x83FF 还没到);处理回调里要防"已死元素"。
5. **监听器数组只增不减**(§3)——设计期就要规划挂载点,不要在循环里挂摘。
6. **PropertyInfo 指针比较的前提**:两侧来自同一 dui70 模块(同一加载基址下的同一 .rdata)。跨 DLL(宿主自己 LoadLibrary 了另一份 dui70)时指针身份失效——正常进程不会发生,但 COM SxS 场景要心里有数。【强推:地址身份机制的推论】

---

## 6. 未解问题(诚实清单)

| # | 问题 | 现状 | 验证路径 |
|---|---|---|---|
| 1 | PropertyInfo flags 各位含义(0x00020000 位出现在 Content/Alpha/Enabled) | 位值已dump,语义未定 | 对照已知属性的已知行为(可继承:LayoutPos?)做消元 |
| 2 | _GetComputedValue 合成优先级(inline > sheet > inherited > default?) | 结构已见,顺序未验证 | 样式表+本地值双设实验(可运行) |
| 3 | 依赖系统 _AddDependency/_GetDependencies 的失效触发时机 | 仅符号级 | 反汇编 _GetDependencies(0x26DD0) + dirty flag 写入点 |
| 4 | Expression 值的求值时机(Expression 类仅 3 个符号,可疑地薄) | 未还原 | CreateExpression 构造链 + 求值虚调用 |
| 5 | cap 数组各项与 ValueType 的完整映射(白名单还是优先级表) | 首项=主类型已实锤,后续项语义未知 | 多类型属性(如 Content 接受 String/Int)交叉实验 |
| 6 | Value 首 DWORD 低 7 位除 bit7(永久)外的标志位 | bit7 实锤,其余未知 | 位扫描 + 构造路径交叉 |
| 7 | Destroy 的 0x83FF 在 duser 侧延迟到哪个泵周期 | duser 侧队列机制已知(深拷贝入 SList),dui70 侧消费时序未验证 | 探针统计 Destroy→gadget 回收的延迟帧数 |
| 8 | PropertyInfo+0x20/+0x28 两个函数指针的用途 | 类型相关(Alpha/Width/MouseWithin 各不同) | 逐个调用观察(疑似 Value 构造/默认值/解析辅助) |

---

## 7. 小结与系列回顾

- **PropertyInfo = 编译期反射常量**(名字/cap 白名单/flags),身份是指针;Element 约 70 个,子类继承;
- **Value = 低位复用引用计数的 variant**(步长 0x80、bit7 永久位、25+ 工厂、15 个单例);
- **Element 不引用计数**——树所有权决定生死;Detach 摘、Destroy 缓期处决(0x83FF);
- **SetValue 统一漏斗**:OnPropertyChanging 否决 → 二分定位 → 引用交接 → 事务登记 → 通知监听;
- **监听器数组快照协议**:只增不减、哑元替换、迭代安全。

至此三篇覆盖了 outline §1/§2/§3/§12 的全部【实锤】结论,并把其中 6 项【强推】升级为指令级【实锤】(defer cookie 机制、Event 字段归属、监听器数组结构、Value 计数编码、Element 无引用计数、OnEvent 快照遍历)。剩下的事件合成/样式合成/布局算法属于任务包 B/D 的教程,见各篇。

---

## 附:证据索引

| 结论 | 证据 | 位置 |
|---|---|---|
| PropertyInfo 布局(name/flags/cap/+0x20/+0x28) | .rdata 字节dump ×5 属性 | .local/build/ui-mental-model/propinfo_table.py 输出(本文 §1.1 转录) |
| name 字符串直读 | PE 映射读 .rdata | 0x1801209E0 = L"Alpha" |
| cap 数组 + UITest 用法(prop->cap->type) | dump + 可运行样本 | UITest/UITest.cpp:153-188 |
| 71 个 *Prop 静态工厂 | 符号表计数 | pinned/symbols.json |
| _GetSpecifiedValue 二分查找 | 反汇编 | 0x18000FF40 起 |
| SetValue→_SetValue 漏斗(虚通知/二分/交接) | 反汇编 | Element::SetValue@0x213C0 → _SetValue@0x22C20 |
| Value::AddRef/Release 计数编码(步长 0x80/bit7/低位标志) | 反汇编 | 0x4ECE0 / 0x24600 / _ZeroRelease@0x24640 |
| RefcountBase 计数(+0x08, 步长1, vtable[1] 析构) | 反汇编 | 0x66720 / 0x533C0 |
| Element::AddRef = 纯 retq | 反汇编 | 0x7ADA0 |
| AddListener/RemoveListener 数组结构与哑元替换 | 反汇编 | 0x1E8E0 / 0x1E1C0 |
| Destroy → 0x83FF EventMsg → DUserPostEvent | 反汇编 | 0x5FE20(cbSize=0x10, msg=0x83FF 常量直读) |
| Detach 摘链/值表清零/-1 标记 | 反汇编 | 0x2FB60 |
| Get/Release 配对、prop 指针比较、属性拦截 | 可运行样本 | UITest/UITest.cpp:574-579, 633-656 |
| ValueType 22 枚举 | 可运行样本 | UITest/UITest.cpp:106-151 |
| 0x83FF 延迟销毁语义(引用) | 既有报告 | duser-deep-dive.md §1.3 |
| defer 事务机制(引用) | `16-startup-and-threading.md` | `16-startup-and-threading.md` §3 |
