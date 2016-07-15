#pragma once

#include "types.h"

namespace DirectUI
{
	struct UpdateCache
	{
		// ??
	};


	class UILIB_API Element
	{
	public:
		Element();
		Element(const Element&);
		//0
		virtual ~Element();

		Element& operator=(const Element &);

		long Initialize(unsigned int, Element *, unsigned long *);
		static long Create(unsigned int, Element *parent, unsigned long *, Element **out);
		//1
		virtual bool IsRTLReading();

		//2
		virtual bool IsContentProtected();

		static long UnRegister(IClassInfo **);

		//3
		const unsigned __int16 *GetContentStringAsDisplayed(Value **);

		//4
		virtual bool OnPropertyChanging(PropertyInfo const *, int, Value *, Value *);
		//5
		virtual bool OnPropertyChanging(PropertyInfo *, int, Value *, Value *);
		//6
		virtual void OnPropertyChanged(PropertyInfo const *, int, Value *, Value *);
		//7
		virtual void OnPropertyChanged(PropertyInfo *, int, Value *, Value *);
		//8
		virtual void OnGroupChanged(int, bool);
		//9
		virtual void OnInput(InputEvent *);
		//10
		virtual void OnKeyFocusMoved(Element *, Element *);
		//11
		virtual void OnMouseFocusMoved(Element *, Element *);
		//12
		virtual void OnDestroy();
		//13
		virtual void OnEvent(Event *);
		//14
		virtual void Paint(HDC, RECT const *, RECT const *, RECT *, RECT *);

		//15
		virtual SIZE GetContentSize(LPSIZE psizl, int, Surface *);

		long Add(Element *);
		long Add(Element *, int(__cdecl*)(const void *, const void *));
		//16
		virtual long Add(Element **, unsigned int);

		long AddListener(IElementListener *);

		unsigned long AddRef();
		static UID AnimationChange();

		void BroadcastEvent(Event *);
		void Detach(DeferCycle *);

		//17
		virtual long Insert(Element **, unsigned int, unsigned int);
		//18
		virtual long Remove(Element **, unsigned int);

		//19
		virtual Element* GetAdjacent(Element*, int, const struct NavReference*, unsigned __int32);

		//20
		virtual bool EnsureVisible(int, int, int, int);

		//21
		virtual void SetKeyFocus(void);

		//22
		virtual unsigned int MessageCallback(GMSG *);

		//23
		virtual long WINAPI QueryInterface(GUID const &, void **);

		//24

		//25
		virtual SIZE _SelfLayoutUpdateDesiredSize(int, int, Surface *);


		long Destroy(bool);
		long DestroyAll(bool);
		void DoubleBuffered(bool);
		void EnableUiaEvents(bool);
		void EndDefer(unsigned long);
		bool EnsureVisible(unsigned int);
		bool EnsureVisible(void);
		Element* FindDescendent(ATOM id);
		void FireEvent(struct Event*, bool, bool);

		bool GetAbsorbsShortcut();
		const unsigned short* GetAccDefAction(Value **);
		const unsigned short* GetAccDesc(Value **);
		const unsigned short* GetAccHelp(Value **);
		const unsigned short* GetAccItemStatus(Value **);
		const unsigned short* GetAccItemType(Value **);
		const unsigned short* GetAccName(Value **);
		const unsigned short* GetAccNameAsDisplayed(Value **);
		const unsigned short* GetAccValue(Value **);

		int GetAccRole();
		int GetAccState();
		bool GetAccessible();
		int GetActive();
		Element* GetRoot();

		// Properties? wtf is this

		static const PropertyInfo* WINAPI AbsorbsShortcutProp();
		static const PropertyInfo* WINAPI AccDefActionProp();
		static const PropertyInfo* WINAPI AccDescProp();
		static const PropertyInfo* WINAPI AccHelpProp();
		static const PropertyInfo* WINAPI AccItemStatusProp();
		static const PropertyInfo* WINAPI AccItemTypeProp();
		static const PropertyInfo* WINAPI AccNameProp();
		static const PropertyInfo* WINAPI AccRoleProp();
		static const PropertyInfo* WINAPI AccStateProp();
		static const PropertyInfo* WINAPI AccValueProp();
		static const PropertyInfo* WINAPI AccessibleProp();
		static const PropertyInfo* WINAPI ActiveProp();
		static const PropertyInfo* WINAPI AlphaProp();
		static const PropertyInfo* WINAPI AnimationProp();
		static const PropertyInfo* WINAPI BackgroundProp();
		static const PropertyInfo* WINAPI BorderColorProp();
		static const PropertyInfo* WINAPI BorderStyleProp();
		static const PropertyInfo* WINAPI BorderThicknessProp();
		static const PropertyInfo* WINAPI ChildrenProp();
		static const PropertyInfo* WINAPI ClassProp();
		static const PropertyInfo* WINAPI CompositedTextProp();
		static const PropertyInfo* WINAPI ContentAlignProp();

		static const PropertyInfo* WINAPI ContentProp();
		static const PropertyInfo* WINAPI CursorProp();
		static const PropertyInfo* WINAPI CustomProp();
		static const PropertyInfo* WINAPI DPIProp();
		static const PropertyInfo* WINAPI DirectionProp();
		static const PropertyInfo* WINAPI DesiredSizeProp();
		static const PropertyInfo* WINAPI ExtentProp();
		static const PropertyInfo* WINAPI ForegroundProp();
		static const PropertyInfo* WINAPI FontFaceProp();
		static const PropertyInfo* WINAPI FontProp();
		static const PropertyInfo* WINAPI FontQualityProp();
		static const PropertyInfo* WINAPI FontSizeProp();
		static const PropertyInfo* WINAPI FontStyleProp();
		static const PropertyInfo* WINAPI FontWeightProp();
		static const PropertyInfo* WINAPI KeyFocusedProp();
		static const PropertyInfo* WINAPI KeyWithinProp();
		static const PropertyInfo* WINAPI LastDSConstProp();
		static const PropertyInfo* WINAPI LayoutPosProp();
		static const PropertyInfo* WINAPI LayoutProp();
		static const PropertyInfo* WINAPI LocationProp();
		static const PropertyInfo* WINAPI HeightProp();
		static const PropertyInfo* WINAPI HighDPIProp();
		static const PropertyInfo* WINAPI IDProp();
		static const PropertyInfo* WINAPI MinSizeProp();
		static const PropertyInfo* WINAPI MouseFocusedProp();
		static const PropertyInfo* WINAPI MouseWithinProp();
		static const PropertyInfo* WINAPI OverhangProp();
		static const PropertyInfo* WINAPI PaddingProp();
		static const PropertyInfo* WINAPI ParentProp();
		static const PropertyInfo* WINAPI PosInLayoutProp();
		static const PropertyInfo* WINAPI SelectedProp();
		static const PropertyInfo* WINAPI ShadowIntensityProp();
		static const PropertyInfo* WINAPI SheetProp();
		static const PropertyInfo* WINAPI ShortcutProp();
		static const PropertyInfo* WINAPI SizeInLayoutProp();
		static const PropertyInfo* WINAPI TextGlowSizeProp();
		static const PropertyInfo* WINAPI TooltipMaxWidthProp();
		static const PropertyInfo* WINAPI TooltipProp();
		static const PropertyInfo* WINAPI VisibleProp();
		static const PropertyInfo* WINAPI WidthProp();
		static const PropertyInfo* WINAPI WindowActiveProp();
		static const PropertyInfo* WINAPI XProp();
		static const PropertyInfo* WINAPI YProp();

		long GetRootRelativeBounds(LPRECT);
		bool GetSelected();
		int GetShadowIntensity();
		StyleSheet* GetSheet();
		int GetShortcut();
		unsigned short GetShortcutChar();
		int GetTextGlowSize();
		bool GetTooltip();
		int GetTooltipMaxWidth();
		Element* GetTopLevel();
		float GetTreeAlphaLevel();
		Value* GetValue( const PropertyInfo* (WINAPI*)(void), int, UpdateCache *);
		Value * GetValue(PropertyInfo const *, int, UpdateCache *);
		bool GetVisible();
		int GetWidth();
		bool GetWindowActive();
		int GetX();
		int GetY();

		bool HasAnimation();
		bool HasBorder();
		bool HasChildren();
		bool HasContent();
		bool HasLayout();
		bool HasMargin();
		bool HasPadding();
		static void InitDefaultFontSize();
		static UID KeyboardNavigate();

		long Insert(Element *, unsigned int);
		
		void InvokeAnimation(int, unsigned int);
		void InvokeAnimation(unsigned int, unsigned int, float, float, bool);
		bool IsCompositedText();
		
		bool IsDefaultCAlign();
		bool IsDefaultCursor();
		bool IsDescendent(Element *);
		bool IsDestroyed();
		bool IsHosted();
		bool IsRTL();
		
		int IsRoot();
		bool IsSelfLayout();
		bool IsValidAccessor(PropertyInfo const *, int, bool);
		static bool IsValidValue(PropertyInfo const *, Value *);
		bool IsWordWrap();
		void MapElementPoint(Element *, POINT const *, LPPOINT);
		static const PropertyInfo* WINAPI MarginProp();

		void MarkNeedsDSUpdate();
		bool NeedsDSUpdate();

		
		

		void PaintBackground(HDC, Value *, RECT const &, RECT const &, RECT const &, RECT const &);
		void PaintBorder(HDC, Value *, RECT *, RECT const &);
		void PaintContent(HDC, RECT const *);
		void PaintFocusRect(HDC, RECT const *, RECT const *);
		void PaintStringContent(HDC, RECT const *, Value *, int);

		void PostEvent(Event *);
		long QueueDefaultAction();
		static long Register();
		unsigned long Release();
		long Remove(Element *);
		long RemoveAll();
		void RemoveListener(IElementListener *);
		long RemoveLocalValue( const PropertyInfo* (WINAPI*)(void));
		long RemoveLocalValue(PropertyInfo const *);

		long SetAbsorbsShortcut(bool);
		long SetAccDefAction(unsigned short const *);
		long SetAccDesc(unsigned short const *);
		long SetAccHelp(unsigned short const *);
		long SetAccItemStatus(unsigned short const *);
		long SetAccItemType(unsigned short const *);
		long SetAccName(unsigned short const *);
		long SetAccRole(int);
		long SetAccState(int);
		long SetAccValue(unsigned short const *);
		long SetAccessible(bool);
		long SetActive(int);
		long SetAlpha(int);
		long SetAnimation(int);
		long SetBackgroundColor(Fill const &);
		long SetBackgroundColor(unsigned long);
		long SetBackgroundColor(unsigned long, unsigned long, unsigned char);
		long SetBackgroundColor(unsigned long, unsigned long, unsigned long, unsigned char);
		long SetBackgroundColor(unsigned short const *, int, int);
		long SetBackgroundStdColor(int);
		long SetBorderColor(unsigned long);
		long SetBorderGradientColor(unsigned long, unsigned long, unsigned char);
		long SetBorderStdColor(int);
		long SetBorderStyle(int);
		long SetBorderThickness(int, int, int, int);
		long SetClass(unsigned short const *);
		static void SetClassInfoPtr(IClassInfo *);
		long SetCompositedText(bool);
		long SetContentAlign(int);
		long SetContentGraphic(unsigned short const *, unsigned char, unsigned int);
		long SetContentGraphic(unsigned short const *, unsigned short, unsigned short);
		long SetContentString(unsigned short const *);
		long SetCursor(unsigned short const *);
		long SetCursorHandle(HICON);
		long SetDirection(int);
		long SetEnabled(bool);
		long SetEncodedContentString(unsigned short const *);
		long SetFont(unsigned short const *);
		long SetFontFace(unsigned short const *);
		long SetFontQuality(int);
		long SetFontSize(int);
		long SetFontStyle(int);
		long SetFontWeight(int);
		long SetForegroundColor(unsigned long);
		long SetForegroundColor(unsigned long, unsigned long, unsigned char);
		long SetForegroundColor(unsigned long, unsigned long, unsigned long, unsigned char);
		long SetForegroundStdColor(int);
		long SetHeight(int);
		long SetID(unsigned short const *);
		long SetLayout(Layout *);
		long SetLayoutPos(int);
		long SetMargin(int, int, int, int);
		long SetMinSize(int, int);
		long SetOverhang(bool);
		long SetPadding(int, int, int, int);
		long SetSelected(bool);
		long SetShadowIntensity(int);
		long SetSheet(StyleSheet *);
		long SetShortcut(int);
		long SetStdCursor(int);
		long SetTextGlowSize(int);
		long SetTooltip(bool);
		long SetTooltipMaxWidth(int);
		long SetValue( const PropertyInfo* (WINAPI*)(void), int, Value *);
		long SetValue(PropertyInfo const *, int, Value *);
		long SetVisible(bool);
		long SetWidth(int);
		long SetWindowActive(bool);
		long SetX(int);
		long SetY(int);

		long SortChildren(int (WINAPI*)(void const *, void const *));
		void StartDefer(unsigned long *);
		void StopAnimation(unsigned int);
		DeferCycle * TestDeferObject();
		bool UiaEvents();
		void UpdateLayout();
		static void _AddDependency(Element *, PropertyInfo const *, int, DepRecs *, DeferCycle *, long *);
		void _ClearNeedsLayout();
		static long _DisplayNodeCallback(struct HGADGET__ *, void *, struct EventMsg *);
		void _EndOptimizedLayoutQ();
		int _GetChangesUpdatePass();
		unsigned int _GetNeedsLayout();
		static int _MarkElementForDS(Element *);
		static int _MarkElementForLayout(Element *, unsigned int);
		static bool _SetGroupChanges(Element *, int, DeferCycle *);
		int _SetNeedsLayout(unsigned int);
		void _StartOptimizedLayoutQ(void);
		static void _TransferGroupFlags(Element *, int);
		struct tagSIZE _UpdateDesiredSize(int, int, Surface *);
		void _UpdateLayoutPosition(int, int);
		void _UpdateLayoutSize(int, int);

	protected:
		//26
		virtual void OnHosted(Element *);
		//27
		virtual void OnUnHosted(Element *);
		//28
		virtual void UpdateTooltip(Element *);
		//29
		virtual void ActivateTooltip(Element *, unsigned long);
		//30
		virtual void RemoveTooltip(Element *);
		//31
		virtual bool GetKeyFocused();

		//32
		virtual IClassInfo *GetClassInfoW();
		//33
		virtual long GetAccessibleImpl(IAccessible **);

		//34
		virtual long DefaultAction();

		//35
		virtual HRESULT WINAPI GetElementProviderImpl(class ElementProvider * *);

		//36
		virtual void HandleUiaDestroyListener();
		//37
		virtual void HandleUiaPropertyListener(PropertyInfo const *, int, Value *, Value *);
		//38
		virtual void HandleUiaPropertyChangingListener(PropertyInfo const *);
		//39
		virtual void HandleUiaEventListener(Event *);


		void MarkHosted();
		void MarkSelfLayout();
		static void _FlushLayout(Element *, DeferCycle *);
		static void _InvalidateCachedDSConstraints(Element *);
		void _OnFontPropChanged(Value *);
		long _RemoveLocalValue( const PropertyInfo* (WINAPI*)(void), bool);
		long _RemoveLocalValue(PropertyInfo const *, bool);
		//virtual void _SelfLayoutDoLayout(int, int);
		long _SetValue( const PropertyInfo* (WINAPI*)(void), int, Value *, bool);
		long _SetValue(PropertyInfo const *, int, Value *, bool);

	private:
		Element* FindDescendentWorker(unsigned short);
		void _SyncBackground();
		void _SyncRedrawStyle();
		void _SyncVisible();
		bool IsPointValid(double, double);
		unsigned short * RemoveShortcutFromName(const String);
		bool TryLinePattern(LPPOINT, const RECT&);
		bool TryPattern(double, double, LPPOINT, const RECT&);
		bool TrySparsePattern(LPPOINT, const RECT&);
		void _BroadcastEventWorker(Event *);
		int _CachedValueIsEqual(const PropertyInfo *, Element *);
		void _GetBuriedSheetDependencies(const PropertyInfo *, Element *, DepRecs *, DeferCycle *, long *);
		void _UpdatePropertyInCache(const PropertyInfo *);
		static void _VoidPCNotifyTree(int, DeferCycle *);
		static IClassInfo *s_pClassInfo;

		void _FlushDS(DeferCycle *);
		Value * _GetComputedValue(PropertyInfo const *, UpdateCache *);
		long _GetDependencies(PropertyInfo const *, int, DepRecs *, int, Value *, DeferCycle *);
		Value * _GetLocalValue(PropertyInfo const *);
		Value * _GetLocalValueFromVM(PropertyInfo const *);
		Value * _GetSpecifiedValue(PropertyInfo const *, UpdateCache *);
		Value * _GetSpecifiedValueIgnoreCache(PropertyInfo const *);
		void _InheritProperties();
		long _PostSourceChange();
		long _PreSourceChange( const PropertyInfo* (WINAPI*)(void), int, Value *, Value *);
		long _PreSourceChange(PropertyInfo const *, int, Value *, Value *);
	};

	

	class UILIB_API ElementWithHWND : public Element
	{
	public:
		ElementWithHWND(const ElementWithHWND &);
		ElementWithHWND();
		virtual ~ElementWithHWND();
		ElementWithHWND& operator=(const ElementWithHWND &);

		static long Create(Element *, unsigned long *, Element **);
		static IClassInfo * GetClassInfoPtr();
		virtual IClassInfo * GetClassInfoW();
		static long Register();
		static void SetClassInfoPtr(IClassInfo *);

	private:
		static IClassInfo *s_pClassInfo;
	};

	class UILIB_API HWNDElement : public ElementWithHWND
	{
	public:
		HWNDElement(const HWNDElement &);
		HWNDElement();
		virtual ~HWNDElement();
		HWNDElement& operator=(const HWNDElement &);

		//0
		virtual void OnPropertyChanged(const PropertyInfo *, int, Value *, Value *);
		//1
		virtual void OnGroupChanged(int, bool);
		//2
		virtual void OnInput(InputEvent *);
		//3
		virtual void OnDestroy();
		//4
		virtual void OnEvent(Event *);
		//5
		virtual void UpdateTooltip(Element *);

		//6
		virtual void ActivateTooltip(Element *, unsigned long);
		//7
		virtual void RemoveTooltip(Element *);

		//8
		virtual IClassInfo * GetClassInfoW();
		//9
		virtual long GetAccessibleImpl(IAccessible **);


		//HWNDElement ÐÂÔöº¯Êý
		//10
		virtual HWND GetHWND();

		//11
		virtual void OnThemeChanged(ThemeChangedEvent *);

		//12
		virtual void OnNoChildWithShortcutFound(KeyboardEvent *);

		//13
		virtual void OnGetDlgCode(LPMSG, LRESULT *);
		//14
		virtual void OnWmThemeChanged(WPARAM wParam, LPARAM lParam);
		//15
		virtual void OnCompositionChanged();

		//16
		virtual bool CanSetFocus();

		static class UID CompositionChange();
		static HRESULT WINAPI Create(HWND, bool, unsigned int, Element *, unsigned long *, Element **pOut);
		//17
		virtual long CreateStyleParser(DUIXmlParser **);
		void DelayActivateTooltip();
		Element * ElementFromPoint(LPPOINT);
		static bool FindShortcut(unsigned short, Element *, Element **, int *, int *, int);
		void FlushWorkingSet();
		static IClassInfo * GetClassInfoPtr();

		static HWNDElement * GetFocusedHWNDElement();

		static Element * GetKeyFocusedElement();
		unsigned short GetUIState();
		bool GetWrapKeyboardNavigate();
		long Initialize(HWND, bool, unsigned int, Element *, unsigned long *);
		bool IsFirstElement(Element *);
		bool IsLastElement(Element *);


		static long Register();
		static void SetClassInfoPtr(IClassInfo *);

		void SetFocus(bool);
		void SetParentSizeControl(bool);
		void SetScreenCenter(bool);
		long SetWrapKeyboardNavigate(bool);
		bool ShowAccel(void);
		bool ShowFocus(void);
		void ShowUIState(bool, bool);
		static class UID ThemeChange();

		void ToggleUIState(bool, bool);
		static const PropertyInfo* WINAPI WrapKeyboardNavigateProp();

		static __int64 StaticWndProc(HWND, UINT uMsg, WPARAM wParam, LPARAM lParam);
		//18
		virtual LRESULT WndProc(HWND, UINT uMsg, WPARAM wParam, LPARAM lParam);

	protected:
		static bool FindShortcutRecursive(unsigned short, Element *, Element **, int *, int *, int);

	private:
		static IClassInfo * s_pClassInfo;
	};
}