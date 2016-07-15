#include "DirectUI.h"

namespace DirectUI
{
	Element::Element()
	{
	}
	Element::Element(const Element &)
	{
	}
	Element::~Element()
	{
	}
	Element & Element::operator=(const Element &)
	{
		// TODO: 在此处插入 return 语句
		return *this;
	}
	long Element::Initialize(unsigned int, Element *, unsigned long *)
	{
		return 0;
	}
	long Element::Create(unsigned int, Element * parent, unsigned long *, Element ** out)
	{
		return 0;
	}
	bool Element::IsRTLReading()
	{
		return false;
	}
	bool Element::IsContentProtected()
	{
		return false;
	}
	long Element::UnRegister(IClassInfo **)
	{
		return 0;
	}
	const unsigned __int16 * Element::GetContentStringAsDisplayed(Value **)
	{
		return nullptr;
	}
	bool Element::OnPropertyChanging(PropertyInfo const *, int, Value *, Value *)
	{
		return false;
	}
	bool Element::OnPropertyChanging(PropertyInfo *, int, Value *, Value *)
	{
		return false;
	}
	void Element::OnPropertyChanged(PropertyInfo const *, int, Value *, Value *)
	{
	}
	void Element::OnPropertyChanged(PropertyInfo *, int, Value *, Value *)
	{
	}
	void Element::OnGroupChanged(int, bool)
	{
	}
	void Element::OnInput(InputEvent *)
	{
	}
	void Element::OnKeyFocusMoved(Element *, Element *)
	{
	}
	void Element::OnMouseFocusMoved(Element *, Element *)
	{
	}
	void Element::OnDestroy()
	{
	}
	void Element::OnEvent(Event *)
	{
	}
	void Element::Paint(HDC, RECT const *, RECT const *, RECT *, RECT *)
	{
	}
	SIZE Element::GetContentSize(LPSIZE psizl, int, Surface *)
	{
		return SIZE();
	}
	long Element::Add(Element *)
	{
		return 0;
	}
	long Element::Add(Element *, int(*)(const void *, const void *))
	{
		return 0;
	}
	long Element::Add(Element **, unsigned int)
	{
		return 0;
	}
	long Element::AddListener(IElementListener *)
	{
		return 0;
	}
	unsigned long Element::AddRef()
	{
		return 0;
	}
	UID Element::AnimationChange()
	{
		return UID();
	}
	void Element::BroadcastEvent(Event *)
	{
	}
	void Element::Detach(DeferCycle *)
	{
	}
	long Element::Insert(Element **, unsigned int, unsigned int)
	{
		return 0;
	}
	long Element::Remove(Element **, unsigned int)
	{
		return 0;
	}
	Element * Element::GetAdjacent(Element *, int, const NavReference *, unsigned __int32)
	{
		return nullptr;
	}
	bool Element::EnsureVisible(int, int, int, int)
	{
		return false;
	}
	void Element::SetKeyFocus(void)
	{
	}
	unsigned int Element::MessageCallback(GMSG *)
	{
		return 0;
	}
	long Element::QueryInterface(GUID const &, void **)
	{
		return 0;
	}
	SIZE Element::_SelfLayoutUpdateDesiredSize(int, int, Surface *)
	{
		return SIZE();
	}
	long Element::Destroy(bool)
	{
		return 0;
	}
	long Element::DestroyAll(bool)
	{
		return 0;
	}
	void Element::DoubleBuffered(bool)
	{
	}
	void Element::EnableUiaEvents(bool)
	{
	}
	void Element::EndDefer(unsigned long)
	{
	}
	bool Element::EnsureVisible(unsigned int)
	{
		return false;
	}
	bool Element::EnsureVisible(void)
	{
		return false;
	}
	Element * Element::FindDescendent(ATOM id)
	{
		return nullptr;
	}
	void Element::FireEvent(Event *, bool, bool)
	{
	}
	bool Element::GetAbsorbsShortcut()
	{
		return false;
	}
	const unsigned short * Element::GetAccDefAction(Value **)
	{
		return nullptr;
	}
	const unsigned short * Element::GetAccDesc(Value **)
	{
		return nullptr;
	}
	const unsigned short * Element::GetAccHelp(Value **)
	{
		return nullptr;
	}
	const unsigned short * Element::GetAccItemStatus(Value **)
	{
		return nullptr;
	}
	const unsigned short * Element::GetAccItemType(Value **)
	{
		return nullptr;
	}
	const unsigned short * Element::GetAccName(Value **)
	{
		return nullptr;
	}
	const unsigned short * Element::GetAccNameAsDisplayed(Value **)
	{
		return nullptr;
	}
	const unsigned short * Element::GetAccValue(Value **)
	{
		return nullptr;
	}
	int Element::GetAccRole()
	{
		return 0;
	}
	int Element::GetAccState()
	{
		return 0;
	}
	bool Element::GetAccessible()
	{
		return false;
	}
	int Element::GetActive()
	{
		return 0;
	}
	Element * Element::GetRoot()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AbsorbsShortcutProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AccDefActionProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AccDescProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AccHelpProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AccItemStatusProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AccItemTypeProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AccNameProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AccRoleProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AccStateProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AccValueProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AccessibleProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::ActiveProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AlphaProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::AnimationProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::BackgroundProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::BorderColorProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::BorderStyleProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::BorderThicknessProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::ChildrenProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::ClassProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::CompositedTextProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::ContentAlignProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::ContentProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::CursorProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::CustomProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::DPIProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::DirectionProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::DesiredSizeProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::ExtentProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::ForegroundProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::FontFaceProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::FontProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::FontQualityProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::FontSizeProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::FontStyleProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::FontWeightProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::KeyFocusedProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::KeyWithinProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::LastDSConstProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::LayoutPosProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::LayoutProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::LocationProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::HeightProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::HighDPIProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::IDProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::MinSizeProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::MouseFocusedProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::MouseWithinProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::OverhangProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::PaddingProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::ParentProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::PosInLayoutProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::SelectedProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::ShadowIntensityProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::SheetProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::ShortcutProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::SizeInLayoutProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::TextGlowSizeProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::TooltipMaxWidthProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::TooltipProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::VisibleProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::WidthProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::WindowActiveProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::XProp()
	{
		return nullptr;
	}
	const PropertyInfo * Element::YProp()
	{
		return nullptr;
	}
	long Element::GetRootRelativeBounds(LPRECT)
	{
		return 0;
	}
	bool Element::GetSelected()
	{
		return false;
	}
	int Element::GetShadowIntensity()
	{
		return 0;
	}
	StyleSheet * Element::GetSheet()
	{
		return nullptr;
	}
	int Element::GetShortcut()
	{
		return 0;
	}
	unsigned short Element::GetShortcutChar()
	{
		return 0;
	}
	int Element::GetTextGlowSize()
	{
		return 0;
	}
	bool Element::GetTooltip()
	{
		return false;
	}
	int Element::GetTooltipMaxWidth()
	{
		return 0;
	}
	Element * Element::GetTopLevel()
	{
		return nullptr;
	}
	float Element::GetTreeAlphaLevel()
	{
		return 0.0f;
	}
	Value * Element::GetValue(const PropertyInfo *(WINAPI*)(void), int, UpdateCache *)
	{
		return nullptr;
	}
	Value * Element::GetValue(PropertyInfo const *, int, UpdateCache *)
	{
		return nullptr;
	}
	bool Element::GetVisible()
	{
		return false;
	}
	int Element::GetWidth()
	{
		return 0;
	}
	bool Element::GetWindowActive()
	{
		return false;
	}
	int Element::GetX()
	{
		return 0;
	}
	int Element::GetY()
	{
		return 0;
	}
	bool Element::HasAnimation()
	{
		return false;
	}
	bool Element::HasBorder()
	{
		return false;
	}
	bool Element::HasChildren()
	{
		return false;
	}
	bool Element::HasContent()
	{
		return false;
	}
	bool Element::HasLayout()
	{
		return false;
	}
	bool Element::HasMargin()
	{
		return false;
	}
	bool Element::HasPadding()
	{
		return false;
	}
	void Element::InitDefaultFontSize()
	{
	}
	UID Element::KeyboardNavigate()
	{
		return UID();
	}
	long Element::Insert(Element *, unsigned int)
	{
		return 0;
	}
	void Element::InvokeAnimation(int, unsigned int)
	{
	}
	void Element::InvokeAnimation(unsigned int, unsigned int, float, float, bool)
	{
	}
	bool Element::IsCompositedText()
	{
		return false;
	}
	bool Element::IsDefaultCAlign()
	{
		return false;
	}
	bool Element::IsDefaultCursor()
	{
		return false;
	}
	bool Element::IsDescendent(Element *)
	{
		return false;
	}
	bool Element::IsDestroyed()
	{
		return false;
	}
	bool Element::IsHosted()
	{
		return false;
	}
	bool Element::IsRTL()
	{
		return false;
	}
	int Element::IsRoot()
	{
		return 0;
	}
	bool Element::IsSelfLayout()
	{
		return false;
	}
	bool Element::IsValidAccessor(PropertyInfo const *, int, bool)
	{
		return false;
	}
	bool Element::IsValidValue(PropertyInfo const *, Value *)
	{
		return false;
	}
	bool Element::IsWordWrap()
	{
		return false;
	}
	void Element::MapElementPoint(Element *, POINT const *, LPPOINT)
	{
	}
	const PropertyInfo * Element::MarginProp()
	{
		return nullptr;
	}
	void Element::MarkNeedsDSUpdate()
	{
	}
	bool Element::NeedsDSUpdate()
	{
		return false;
	}
	void Element::PaintBackground(HDC, Value *, RECT const &, RECT const &, RECT const &, RECT const &)
	{
	}
	void Element::PaintBorder(HDC, Value *, RECT *, RECT const &)
	{
	}
	void Element::PaintContent(HDC, RECT const *)
	{
	}
	void Element::PaintFocusRect(HDC, RECT const *, RECT const *)
	{
	}
	void Element::PaintStringContent(HDC, RECT const *, Value *, int)
	{
	}
	void Element::PostEvent(Event *)
	{
	}
	long Element::QueueDefaultAction()
	{
		return 0;
	}
	long Element::Register()
	{
		return 0;
	}
	unsigned long Element::Release()
	{
		return 0;
	}
	long Element::Remove(Element *)
	{
		return 0;
	}
	long Element::RemoveAll()
	{
		return 0;
	}
	void Element::RemoveListener(IElementListener *)
	{
	}
	long Element::RemoveLocalValue(const PropertyInfo *(WINAPI*)(void))
	{
		return 0;
	}
	long Element::RemoveLocalValue(PropertyInfo const *)
	{
		return 0;
	}
	long Element::SetAbsorbsShortcut(bool)
	{
		return 0;
	}
	long Element::SetAccDefAction(unsigned short const *)
	{
		return 0;
	}
	long Element::SetAccDesc(unsigned short const *)
	{
		return 0;
	}
	long Element::SetAccHelp(unsigned short const *)
	{
		return 0;
	}
	long Element::SetAccItemStatus(unsigned short const *)
	{
		return 0;
	}
	long Element::SetAccItemType(unsigned short const *)
	{
		return 0;
	}
	long Element::SetAccName(unsigned short const *)
	{
		return 0;
	}
	long Element::SetAccRole(int)
	{
		return 0;
	}
	long Element::SetAccState(int)
	{
		return 0;
	}
	long Element::SetAccValue(unsigned short const *)
	{
		return 0;
	}
	long Element::SetAccessible(bool)
	{
		return 0;
	}
	long Element::SetActive(int)
	{
		return 0;
	}
	long Element::SetAlpha(int)
	{
		return 0;
	}
	long Element::SetAnimation(int)
	{
		return 0;
	}
	long Element::SetBackgroundColor(Fill const &)
	{
		return 0;
	}
	long Element::SetBackgroundColor(unsigned long)
	{
		return 0;
	}
	long Element::SetBackgroundColor(unsigned long, unsigned long, unsigned char)
	{
		return 0;
	}
	long Element::SetBackgroundColor(unsigned long, unsigned long, unsigned long, unsigned char)
	{
		return 0;
	}
	long Element::SetBackgroundColor(unsigned short const *, int, int)
	{
		return 0;
	}
	long Element::SetBackgroundStdColor(int)
	{
		return 0;
	}
	long Element::SetBorderColor(unsigned long)
	{
		return 0;
	}
	long Element::SetBorderGradientColor(unsigned long, unsigned long, unsigned char)
	{
		return 0;
	}
	long Element::SetBorderStdColor(int)
	{
		return 0;
	}
	long Element::SetBorderStyle(int)
	{
		return 0;
	}
	long Element::SetBorderThickness(int, int, int, int)
	{
		return 0;
	}
	long Element::SetClass(unsigned short const *)
	{
		return 0;
	}
	void Element::SetClassInfoPtr(IClassInfo *)
	{
	}
	long Element::SetCompositedText(bool)
	{
		return 0;
	}
	long Element::SetContentAlign(int)
	{
		return 0;
	}
	long Element::SetContentGraphic(unsigned short const *, unsigned char, unsigned int)
	{
		return 0;
	}
	long Element::SetContentGraphic(unsigned short const *, unsigned short, unsigned short)
	{
		return 0;
	}
	long Element::SetContentString(unsigned short const *)
	{
		return 0;
	}
	long Element::SetCursor(unsigned short const *)
	{
		return 0;
	}
	long Element::SetCursorHandle(HICON)
	{
		return 0;
	}
	long Element::SetDirection(int)
	{
		return 0;
	}
	long Element::SetEnabled(bool)
	{
		return 0;
	}
	long Element::SetEncodedContentString(unsigned short const *)
	{
		return 0;
	}
	long Element::SetFont(unsigned short const *)
	{
		return 0;
	}
	long Element::SetFontFace(unsigned short const *)
	{
		return 0;
	}
	long Element::SetFontQuality(int)
	{
		return 0;
	}
	long Element::SetFontSize(int)
	{
		return 0;
	}
	long Element::SetFontStyle(int)
	{
		return 0;
	}
	long Element::SetFontWeight(int)
	{
		return 0;
	}
	long Element::SetForegroundColor(unsigned long)
	{
		return 0;
	}
	long Element::SetForegroundColor(unsigned long, unsigned long, unsigned char)
	{
		return 0;
	}
	long Element::SetForegroundColor(unsigned long, unsigned long, unsigned long, unsigned char)
	{
		return 0;
	}
	long Element::SetForegroundStdColor(int)
	{
		return 0;
	}
	long Element::SetHeight(int)
	{
		return 0;
	}
	long Element::SetID(unsigned short const *)
	{
		return 0;
	}
	long Element::SetLayout(Layout *)
	{
		return 0;
	}
	long Element::SetLayoutPos(int)
	{
		return 0;
	}
	long Element::SetMargin(int, int, int, int)
	{
		return 0;
	}
	long Element::SetMinSize(int, int)
	{
		return 0;
	}
	long Element::SetOverhang(bool)
	{
		return 0;
	}
	long Element::SetPadding(int, int, int, int)
	{
		return 0;
	}
	long Element::SetSelected(bool)
	{
		return 0;
	}
	long Element::SetShadowIntensity(int)
	{
		return 0;
	}
	long Element::SetSheet(StyleSheet *)
	{
		return 0;
	}
	long Element::SetShortcut(int)
	{
		return 0;
	}
	long Element::SetStdCursor(int)
	{
		return 0;
	}
	long Element::SetTextGlowSize(int)
	{
		return 0;
	}
	long Element::SetTooltip(bool)
	{
		return 0;
	}
	long Element::SetTooltipMaxWidth(int)
	{
		return 0;
	}
	long Element::SetValue(const PropertyInfo *(WINAPI*)(void), int, Value *)
	{
		return 0;
	}
	long Element::SetValue(PropertyInfo const *, int, Value *)
	{
		return 0;
	}
	long Element::SetVisible(bool)
	{
		return 0;
	}
	long Element::SetWidth(int)
	{
		return 0;
	}
	long Element::SetWindowActive(bool)
	{
		return 0;
	}
	long Element::SetX(int)
	{
		return 0;
	}
	long Element::SetY(int)
	{
		return 0;
	}
	long Element::SortChildren(int(WINAPI*)(void const *, void const *))
	{
		return 0;
	}
	void Element::StartDefer(unsigned long *)
	{
	}
	void Element::StopAnimation(unsigned int)
	{
	}
	DeferCycle * Element::TestDeferObject()
	{
		return nullptr;
	}
	bool Element::UiaEvents()
	{
		return false;
	}
	void Element::UpdateLayout()
	{
	}
	void Element::_AddDependency(Element *, PropertyInfo const *, int, DepRecs *, DeferCycle *, long *)
	{
	}
	void Element::_ClearNeedsLayout()
	{
	}
	long Element::_DisplayNodeCallback(HGADGET__ *, void *, EventMsg *)
	{
		return 0;
	}
	void Element::_EndOptimizedLayoutQ()
	{
	}
	int Element::_GetChangesUpdatePass()
	{
		return 0;
	}
	unsigned int Element::_GetNeedsLayout()
	{
		return 0;
	}
	int Element::_MarkElementForDS(Element *)
	{
		return 0;
	}
	int Element::_MarkElementForLayout(Element *, unsigned int)
	{
		return 0;
	}
	bool Element::_SetGroupChanges(Element *, int, DeferCycle *)
	{
		return false;
	}
	int Element::_SetNeedsLayout(unsigned int)
	{
		return 0;
	}
	void Element::_StartOptimizedLayoutQ(void)
	{
	}
	void Element::_TransferGroupFlags(Element *, int)
	{
	}
	tagSIZE Element::_UpdateDesiredSize(int, int, Surface *)
	{
		return tagSIZE();
	}
	void Element::_UpdateLayoutPosition(int, int)
	{
	}
	void Element::_UpdateLayoutSize(int, int)
	{
	}
	void Element::OnHosted(Element *)
	{
	}
	void Element::OnUnHosted(Element *)
	{
	}
	void Element::UpdateTooltip(Element *)
	{
	}
	void Element::ActivateTooltip(Element *, unsigned long)
	{
	}
	void Element::RemoveTooltip(Element *)
	{
	}
	bool Element::GetKeyFocused()
	{
		return false;
	}
	IClassInfo * Element::GetClassInfoW()
	{
		return nullptr;
	}
	long Element::GetAccessibleImpl(IAccessible **)
	{
		return 0;
	}
	long Element::DefaultAction()
	{
		return 0;
	}
	HRESULT Element::GetElementProviderImpl(ElementProvider **)
	{
		return E_NOTIMPL;
	}
	void Element::HandleUiaDestroyListener()
	{
	}
	void Element::HandleUiaPropertyListener(PropertyInfo const *, int, Value *, Value *)
	{
	}
	void Element::HandleUiaPropertyChangingListener(PropertyInfo const *)
	{
	}
	void Element::HandleUiaEventListener(Event *)
	{
	}
	void Element::MarkHosted()
	{
	}
	void Element::MarkSelfLayout()
	{
	}
	void Element::_FlushLayout(Element *, DeferCycle *)
	{
	}
	void Element::_InvalidateCachedDSConstraints(Element *)
	{
	}
	void Element::_OnFontPropChanged(Value *)
	{
	}
	long Element::_RemoveLocalValue(const PropertyInfo *(WINAPI*)(void), bool)
	{
		return 0;
	}
	long Element::_RemoveLocalValue(PropertyInfo const *, bool)
	{
		return 0;
	}
	long Element::_SetValue(const PropertyInfo *(WINAPI*)(void), int, Value *, bool)
	{
		return 0;
	}
	long Element::_SetValue(PropertyInfo const *, int, Value *, bool)
	{
		return 0;
	}
	Element * Element::FindDescendentWorker(unsigned short)
	{
		return nullptr;
	}
	void Element::_SyncBackground()
	{
	}
	void Element::_SyncRedrawStyle()
	{
	}
	void Element::_SyncVisible()
	{
	}
	bool Element::IsPointValid(double, double)
	{
		return false;
	}
	unsigned short * Element::RemoveShortcutFromName(const String)
	{
		return nullptr;
	}
	bool Element::TryLinePattern(LPPOINT, const RECT &)
	{
		return false;
	}
	bool Element::TryPattern(double, double, LPPOINT, const RECT &)
	{
		return false;
	}
	bool Element::TrySparsePattern(LPPOINT, const RECT &)
	{
		return false;
	}
	void Element::_BroadcastEventWorker(Event *)
	{
	}
	int Element::_CachedValueIsEqual(const PropertyInfo *, Element *)
	{
		return 0;
	}
	void Element::_GetBuriedSheetDependencies(const PropertyInfo *, Element *, DepRecs *, DeferCycle *, long *)
	{
	}
	void Element::_UpdatePropertyInCache(const PropertyInfo *)
	{
	}
	void Element::_VoidPCNotifyTree(int, DeferCycle *)
	{
	}
	void Element::_FlushDS(DeferCycle *)
	{
	}
	Value * Element::_GetComputedValue(PropertyInfo const *, UpdateCache *)
	{
		return nullptr;
	}
	long Element::_GetDependencies(PropertyInfo const *, int, DepRecs *, int, Value *, DeferCycle *)
	{
		return 0;
	}
	Value * Element::_GetLocalValue(PropertyInfo const *)
	{
		return nullptr;
	}
	Value * Element::_GetLocalValueFromVM(PropertyInfo const *)
	{
		return nullptr;
	}
	Value * Element::_GetSpecifiedValue(PropertyInfo const *, UpdateCache *)
	{
		return nullptr;
	}
	Value * Element::_GetSpecifiedValueIgnoreCache(PropertyInfo const *)
	{
		return nullptr;
	}
	void Element::_InheritProperties()
	{
	}
	long Element::_PostSourceChange()
	{
		return 0;
	}
	long Element::_PreSourceChange(const PropertyInfo *(WINAPI*)(void), int, Value *, Value *)
	{
		return 0;
	}
	long Element::_PreSourceChange(PropertyInfo const *, int, Value *, Value *)
	{
		return 0;
	}
	ElementWithHWND::ElementWithHWND(const ElementWithHWND &)
	{
	}
	ElementWithHWND::ElementWithHWND()
	{
	}
	ElementWithHWND::~ElementWithHWND()
	{
	}
	ElementWithHWND & ElementWithHWND::operator=(const ElementWithHWND &)
	{
		// TODO: 在此处插入 return 语句
		return *this;
	}
	long ElementWithHWND::Create(Element *, unsigned long *, Element **)
	{
		return 0;
	}
	IClassInfo * ElementWithHWND::GetClassInfoPtr()
	{
		return nullptr;
	}
	IClassInfo * ElementWithHWND::GetClassInfoW()
	{
		return nullptr;
	}
	long ElementWithHWND::Register()
	{
		return 0;
	}
	void ElementWithHWND::SetClassInfoPtr(IClassInfo *)
	{
	}
}
