#pragma once

namespace DirectUI
{
	enum _DUI_PARSE_STATE
	{

	};

	typedef _DUI_PARSE_STATE DUI_PARSE_STATE;

	struct IXmlReader
	{
		// ??
	};

	struct LINEINFO
	{

	};

	struct XMLParserCond
	{

	};

	class Schema 
	{
	public:
		enum Pattern
		{
		};
		/*
public: class DirectUI::Schema & __ptr64 __cdecl DirectUI::Schema::operator=(class DirectUI::Schema const & __ptr64) __ptr64
public: static int DirectUI::Schema::AcceleratorKeyProperty
public: static int DirectUI::Schema::AccessKeyProperty
public: static int DirectUI::Schema::AsyncContentLoadedEvent
public: static int DirectUI::Schema::AutomationFocusChangedEvent
public: static int DirectUI::Schema::AutomationIdProperty
public: static int DirectUI::Schema::AutomationPropertyChangedEvent
public: static int DirectUI::Schema::BoundingRectangleProperty
public: static int DirectUI::Schema::ButtonControlType
public: static int DirectUI::Schema::CalendarControlType
public: static int DirectUI::Schema::CheckBoxControlType
public: static int DirectUI::Schema::ClassNameProperty
public: static int DirectUI::Schema::ClickablePointProperty
public: static int DirectUI::Schema::ComboBoxControlType
public: static int DirectUI::Schema::ControlTypeProperty
public: static long __cdecl DirectUI::Schema::CreatePatternProvider(enum DirectUI::Schema::Pattern,class DirectUI::ElementProvider* __ptr64,struct IUnknown* __ptr64* __ptr64)
public: static int DirectUI::Schema::CultureProperty
public: static int DirectUI::Schema::CustomControlType
public: static int DirectUI::Schema::DataGridControlType
public: static int DirectUI::Schema::DataItemControlType
public: static int DirectUI::Schema::DockPattern
public: static int DirectUI::Schema::DocumentControlType
public: static int DirectUI::Schema::EditControlType
public: static enum DirectUI::Schema::Event __cdecl DirectUI::Schema::EventFromEventId(int)
public: static int DirectUI::Schema::ExpandCollapsePattern
public: static int DirectUI::Schema::ExpandCollapse_ExpandCollapseState_Property
public: static int DirectUI::Schema::FrameworkId
private: static long __cdecl DirectUI::Schema::GetProcs(void)
public: static int DirectUI::Schema::GridItemPattern
public: static int DirectUI::Schema::GridItem_ColumnSpan_Property
public: static int DirectUI::Schema::GridItem_Column_Property
public: static int DirectUI::Schema::GridItem_Parent_Property
public: static int DirectUI::Schema::GridItem_RowSpan_Property
public: static int DirectUI::Schema::GridItem_Row_Property
public: static int DirectUI::Schema::GridPattern
public: static int DirectUI::Schema::Grid_ColumnCount_Property
public: static int DirectUI::Schema::Grid_RowCount_Property
public: static int DirectUI::Schema::GroupControlType
public: static int DirectUI::Schema::HasKeyboardFocusProperty
public: static int DirectUI::Schema::HeaderControlType
public: static int DirectUI::Schema::HeaderItemControlType
public: static int DirectUI::Schema::HelpTextProperty
public: static int DirectUI::Schema::HyperlinkControlType
public: static int DirectUI::Schema::ImageControlType
public: static long __cdecl DirectUI::Schema::Init(void)
public: static int DirectUI::Schema::InvokeInvokedEvent
public: static int DirectUI::Schema::InvokePattern
public: static int DirectUI::Schema::IsContentElementProperty
public: static int DirectUI::Schema::IsControlElementProperty
public: static int DirectUI::Schema::IsEnabledProperty
public: static int DirectUI::Schema::IsKeyboardFocusableProperty
public: static int DirectUI::Schema::IsOffscreen
public: static int DirectUI::Schema::IsPasswordProperty
protected: long __cdecl DirectUI::ElementProxy::IsPatternSupported(enum DirectUI::Schema::Pattern,bool* __ptr64) __ptr64
public: static int DirectUI::Schema::ItemContainerPattern
public: static int DirectUI::Schema::ItemStatusProperty
public: static int DirectUI::Schema::ItemTypeProperty
public: static int DirectUI::Schema::LabeledByProperty
public: static int DirectUI::Schema::LayoutInvalidatedEvent
public: static int DirectUI::Schema::ListControlType
public: static int DirectUI::Schema::ListItemControlType
public: static int DirectUI::Schema::LocalizedControlTypeProperty
public: static int __cdecl DirectUI::Schema::LookupAccessibleRole(int,bool* __ptr64)
private: static long __cdecl DirectUI::Schema::LookupControlInfos(void)
private: static long __cdecl DirectUI::Schema::LookupEventInfos(void)
private: static long __cdecl DirectUI::Schema::LookupPatternInfos(void)
private: static long __cdecl DirectUI::Schema::LookupPropertyInfos(void)
public: static int DirectUI::Schema::MenuBarControlType
public: static int DirectUI::Schema::MenuClosedEvent
public: static int DirectUI::Schema::MenuControlType
public: static int DirectUI::Schema::MenuItemControlType
public: static int DirectUI::Schema::MenuOpenedEvent
public: static int DirectUI::Schema::MultipleViewPattern
public: static int DirectUI::Schema::NameProperty
public: static int DirectUI::Schema::NewNativeWindowHandleProperty
public: static int DirectUI::Schema::NullControlType
public: static int DirectUI::Schema::Orientation
public: static int DirectUI::Schema::PaneControlType
public: static enum DirectUI::Schema::Pattern __cdecl DirectUI::Schema::PatternFromPatternId(int)
public: static bool (__cdecl*__cdecl DirectUI::Schema::PfnIsSupportedFromPattern(enum DirectUI::Schema::Pattern))(class DirectUI::Element* __ptr64)
public: static int DirectUI::Schema::ProcessIdProperty
public: static int DirectUI::Schema::ProgressBarControlType
public: static int DirectUI::Schema::RadioButtonControlType
public: static int DirectUI::Schema::RangeValuePattern
public: static int DirectUI::Schema::RangeValue_IsReadOnly_Property
public: static int DirectUI::Schema::RangeValue_LargeChange_Property
public: static int DirectUI::Schema::RangeValue_Maximum_Property
public: static int DirectUI::Schema::RangeValue_Minimum_Property
public: static int DirectUI::Schema::RangeValue_SmallChange_Property
public: static int DirectUI::Schema::RangeValue_Value_Property
public: static int DirectUI::Schema::RuntimeIdProperty
public: static int DirectUI::Schema::ScrollBarControlType
public: static int DirectUI::Schema::ScrollItemPattern
public: static int DirectUI::Schema::ScrollPattern
public: static int DirectUI::Schema::Scroll_HorizontalScrollPercent_Property
public: static int DirectUI::Schema::Scroll_HorizontalViewSize_Property
public: static int DirectUI::Schema::Scroll_HorizontallyScrollable_Property
public: static int DirectUI::Schema::Scroll_VerticalScrollPercent_Property
public: static int DirectUI::Schema::Scroll_VerticalViewSize_Property
public: static int DirectUI::Schema::Scroll_VerticallyScrollable_Property
public: static int DirectUI::Schema::SelectionInvalidatedEvent
public: static int DirectUI::Schema::SelectionItemElementAddedToSelectionEvent
public: static int DirectUI::Schema::SelectionItemElementRemovedFromSelectionEvent
public: static int DirectUI::Schema::SelectionItemElementSelectedEvent
public: static int DirectUI::Schema::SelectionItemPattern
public: static int DirectUI::Schema::SelectionItem_IsSelected_Property
public: static int DirectUI::Schema::SelectionItem_SelectionContainer_Property
public: static int DirectUI::Schema::SelectionPattern
public: static int DirectUI::Schema::Selection_CanSelectMultiple_Property
public: static int DirectUI::Schema::Selection_IsSelectionRequired_Property
public: static int DirectUI::Schema::Selection_Selection_Property
public: static int DirectUI::Schema::SeparatorControlType
public: static int DirectUI::Schema::SliderControlType
public: static int DirectUI::Schema::SpinnerControlType
public: static int DirectUI::Schema::SplitButtonControlType
public: static int DirectUI::Schema::StatusBarControlType
public: static int DirectUI::Schema::StructureChangedEvent
public: static int DirectUI::Schema::TabControlType
public: static int DirectUI::Schema::TabItemControlType
public: static int DirectUI::Schema::TableControlType
public: static int DirectUI::Schema::TableItemPattern
public: static int DirectUI::Schema::TableItem_ColumnHeaderItems_Property
public: static int DirectUI::Schema::TableItem_RowHeaderItems_Property
public: static int DirectUI::Schema::TablePattern
public: static int DirectUI::Schema::Table_ColumnHeaders_Property
public: static int DirectUI::Schema::Table_RowHeaders_Property
public: static int DirectUI::Schema::Table_RowOrColumnMajor_Property
public: static int DirectUI::Schema::TextControlType
public: static int DirectUI::Schema::TextPattern
public: static int DirectUI::Schema::TextTextSelectionChangedEvent
public: static int DirectUI::Schema::ThumbControlType
public: static int DirectUI::Schema::TitleBarControlType
public: static int DirectUI::Schema::TogglePattern
public: static int DirectUI::Schema::Toggle_ToggleState_Property
public: static int DirectUI::Schema::ToolBarControlType
public: static int DirectUI::Schema::ToolTipClosedEvent
public: static int DirectUI::Schema::ToolTipControlType
public: static int DirectUI::Schema::ToolTipOpenedEvent
public: void __cdecl DirectUI::ElementProvider::TossPatternProvider(enum DirectUI::Schema::Pattern) __ptr64
public: static int DirectUI::Schema::TransformPattern
public: static int DirectUI::Schema::TreeControlType
public: static int DirectUI::Schema::TreeItemControlType
public: static long (__cdecl* __ptr64 DirectUI::Schema::UiaHostProviderFromHwnd)(struct HWND__* __ptr64,struct IRawElementProviderSimple* __ptr64* __ptr64)
public: static int (__cdecl* __ptr64 DirectUI::Schema::UiaLookupId)(enum AutomationIdentifierType,struct _GUID const* __ptr64)
public: static long (__cdecl* __ptr64 DirectUI::Schema::UiaRaiseAutomationEvent)(struct IRawElementProviderSimple* __ptr64,int)
public: static long (__cdecl* __ptr64 DirectUI::Schema::UiaRaiseAutomationPropertyChangedEvent)(struct IRawElementProviderSimple* __ptr64,int,struct tagVARIANT,struct tagVARIANT)
public: static long (__cdecl* __ptr64 DirectUI::Schema::UiaRaiseStructureChangedEvent)(struct IRawElementProviderSimple* __ptr64,enum StructureChangeType,int* __ptr64,int)
public: static __int64 (__cdecl* __ptr64 DirectUI::Schema::UiaReturnRawElementProvider)(struct HWND__* __ptr64,unsigned __int64,__int64,struct IRawElementProviderSimple* __ptr64)
public: static int DirectUI::Schema::ValuePattern
public: static int DirectUI::Schema::Value_IsReadOnly_Property
public: static int DirectUI::Schema::Value_Value_Property
public: static int DirectUI::Schema::VirtualizedItemPattern
private: static bool __cdecl DirectUI::EventManager::WantEvent(enum DirectUI::Schema::Event,int)
public: static bool __cdecl DirectUI::EventManager::WantEvent(enum DirectUI::Schema::Event)
public: static int DirectUI::Schema::WindowControlType
public: static int DirectUI::Schema::WindowPattern
public: static int DirectUI::Schema::WindowWindowClosedEvent
public: static int DirectUI::Schema::WindowWindowOpenedEvent
private: static struct DirectUI::Schema::RoleMap const* const DirectUI::Schema::_roleMapping
private: static struct DirectUI::Schema::ControlInfo const* const DirectUI::Schema::g_controlInfoTable
private: static struct DirectUI::Schema::EventInfo const* const DirectUI::Schema::g_eventInfoTable
private: static struct DirectUI::Schema::EventMap const* const DirectUI::Schema::g_eventMapping
private: static bool DirectUI::Schema::g_fInited
private: static struct DirectUI::Schema::PatternInfo const* const DirectUI::Schema::g_patternInfoTable
private: static struct DirectUI::Schema::PatternMap const* const DirectUI::Schema::g_patternMapping
private: static struct DirectUI::Schema::const PropertyInfo* const DirectUI::Schema::g_propertyInfoTable
*/
	};

	typedef Value* (WINAPI* GetSheetCallback)(UCString, void*);
	typedef void ( WINAPI* ParseErrorCallback)(UCString, UCString, int, void*);
	typedef bool ( WINAPI* UnknownAttrCallback)(UCString, void*);

	namespace ParserTools
	{
		class ExprNode
		{
		public:

		};

		class ValueParser
		{
		public:
		};
	}

	class UILIB_API DUIXmlParser
	{
	public:
		DUIXmlParser(const DUIXmlParser &);
		DUIXmlParser();
		virtual ~DUIXmlParser();

		DUIXmlParser& operator=( const DUIXmlParser & );
	
		// Callback defines
		/*
		
		*/
		static long WINAPI Create(_Inout_ DUIXmlParser** pXmlParser, _In_opt_ GetSheetCallback, _In_opt_ void*sheetParam, _In_opt_ ParseErrorCallback, _In_opt_ void*parseErrorParam);
		long CreateElement(UCString,class Element*, class Element*, unsigned long*, class Element**out);
		
		void Destroy();
		void EnableDesignMode();
		GetSheetCallback GetGetSheetCallback();
		HINSTANCE GetHInstance();
			
		HINSTANCE GetResourceHInstance();
		long GetSheet(UCString, Value**);
		void* GetSheetContext();
		
		long LookupElement(IXmlReader*, UCString, HINSTANCE,class IClassInfo**);
		long LookupElement(LINEINFO, UCString, HINSTANCE, class IClassInfo**);

		void SetDefaultHInstance(HINSTANCE);
		
		void SetGetSheetCallback(GetSheetCallback);
		void SetParseErrorCallback(ParseErrorCallback, void*);
		void SetUnknownAttrCallback(bool (__cdecl*)(UCString, void*), void*);

		long SetPreprocessedXML(UCString, HINSTANCE, HINSTANCE);
		void SetUnavailableIcon(HICON);

		HRESULT SetXML(UCString szXML, HINSTANCE hModule, HINSTANCE/*0x10000000 作用未知*/);

		//其资源必须在"UIFILE"类型中
		HRESULT SetXMLFromResource(UINT uID, HINSTANCE hModule, HINSTANCE/*0x10000000 作用未知*/);
		HRESULT SetXMLFromResource(UCString szID, HINSTANCE hModule, HINSTANCE/*0x10000000 作用未知*/);

		long UpdateSheets(Element*);
		void _DestroyTables();
		long _InitializeTables();

		// exported for: int, unsigned long, Value*, RECT
		template<typename T>
		struct FunctionDefinition 
		{
			FunctionDefinition<T>& operator=(const FunctionDefinition<T> &);
		};

		union ParsedArg
		{
			// ??
		};
		
	protected:
		long _EnterOnCurrentThread();
		LINEINFO _GetLineInfo(IXmlReader*);

		long AddRulesToStyleSheet(IXmlReader*, StyleSheet*, UCString, DynamicArray<XMLParserCond, 0>*, DynamicArray<UString, 0>*);
		long CreateLayout(const ParserTools::ExprNode*, long (__cdecl*)(int, int*, Value**));
		long CreateStyleSheet(IXmlReader*, UCString, StyleSheet**);
		long CreateXmlReader(IXmlReader**);
		long CreateXmlReaderFromHGLOBAL(void*, IXmlReader**);
		long CreateXmlReaderInputWithEncodingName(IStream*, UCString, IUnknown**);
		long GetParserCommon(DUIXmlParser**);
		long GetPropValPairInfo(IXmlReader*, IClassInfo*, UCString, UCString,class PropertyInfo**, Value**);
		long GetPropValPairInfo(LINEINFO, IClassInfo*, UCString, UCString, const PropertyInfo**, Value**);
		long GetValueParser(ParserTools::ValueParser**);
		static long GetXmlLiteDll(HINSTANCE*);
		long Initialize();
		long InitializeParserFromXmlLiteReader(IXmlReader*);
		static bool IsThemeClassName(const ParserTools::ExprNode*);
		long MapPropertyEnumValue(const class EnumMap*, UCString, int*);
		long MapPropertyNameToPropertyInfo(LINEINFO, IClassInfo*, UCString, const PropertyInfo**);
		long ParseARGBColor(const ParserTools::ExprNode*, unsigned long*);
		long ParseArgs(const ParserTools::ExprNode*, ParsedArg*, unsigned int, const char*);
		long ParseAtomValue(const ParserTools::ExprNode*, Value**);
		long ParseBoolValue(const ParserTools::ExprNode*, Value**);
		long ParseColor(const ParserTools::ExprNode*, unsigned long*);
		long ParseDFCFill(const ParserTools::ExprNode*, Value**);
		long ParseDTBFill(const ParserTools::ExprNode*, Value**);
		long ParseFillValue(const ParserTools::ExprNode*, Value**);
		long ParseFunction(UCString, const ParserTools::ExprNode*, ParsedArg*, unsigned int, const char*);
		long ParseGTCColor(const ParserTools::ExprNode*, unsigned long*);
		long ParseGTFStr(const ParserTools::ExprNode*, Value**);
		long ParseGTMarRect(const ParserTools::ExprNode*, LPRECT);
		long ParseGTMetInt(const ParserTools::ExprNode*, int*);
		long ParseGradientFill(const ParserTools::ExprNode*, Value**);
		long ParseGraphicGraphic(const ParserTools::ExprNode*, Value**);
		long ParseGraphicHelper(bool,const ParserTools::ExprNode*, Value**);
		long ParseGraphicValue(const ParserTools::ExprNode*, Value**);
		long ParseIconGraphic(const ParserTools::ExprNode*, Value**);
		long ParseImageGraphic(const ParserTools::ExprNode*, Value**);
		long ParseIntValue(const ParserTools::ExprNode*, Value**);
		long ParseLayoutValue(const ParserTools::ExprNode*);
		long ParseLibrary(const ParserTools::ExprNode*, HINSTANCE*);
		long ParseLiteral(const ParserTools::ExprNode*, UCString*);
		long ParseLiteralColor(UCString, unsigned long*);
		long ParseLiteralColorInt(UCString, int*);
		long ParseLiteralNumber(UCString, int*);
		long ParseMagnitude(UCString, int*);
		long ParseNumber(const ParserTools::ExprNode*, int*);
		long ParsePointValue(const ParserTools::ExprNode*, Value**);
		long ParseQuotedString(const ParserTools::ExprNode*, UCString*);
		long ParseRGBColor(const ParserTools::ExprNode*, unsigned long*);
		long ParseRect(const ParserTools::ExprNode*, LPRECT);
		long ParseRectRect(const ParserTools::ExprNode*, LPRECT);
		long ParseRectValue(const ParserTools::ExprNode*, Value**);
		long ParseResStr(const ParserTools::ExprNode*, Value**);
		long ParseResid(const ParserTools::ExprNode*, UCString*);
		long ParseSGraphicGraphic(const ParserTools::ExprNode*, Value**);
		long ParseSGraphicHelper(bool,const ParserTools::ExprNode*, Value**);
		long ParseSizeValue(const ParserTools::ExprNode*, Value**);
		long ParseStringValue(const ParserTools::ExprNode*, Value**);
		long ParseStyleSheets(IXmlReader*);
		long ParseSysMetricInt(const ParserTools::ExprNode*, int*);
		long ParseSysMetricStr(const ParserTools::ExprNode*, Value**);
		long ParseTheme(const ParserTools::ExprNode*, void**);
		static int QuerySysMetric(int);
		static UCString QuerySysMetricStr(int, UString, unsigned int);
		void ReturnValueParser(ParserTools::ValueParser*);
		void SendParseError(UCString, UCString, int, int, long);
		void SendParseError(UCString, UCString, IXmlReader*, long);
		void _LeaveOnCurrentThread();

		long _RecordElementLayout(IXmlReader*, UCString);
		long _RecordElementStyleSheet(UCString, bool);
		long _RecordElementTrees(IXmlReader*);
		long _RecordElementWithChildren(IXmlReader*, bool, UString*);
		long _RecordInstantiateElement(IXmlReader*, UString*);
		long _RecordSetElementProperties(IXmlReader*);
		long _RecordSetValue(IXmlReader*, UCString, UCString);

		static FunctionDefinition<unsigned long> const* const s_fdClr;
		static FunctionDefinition<Value*> const* const s_fdFill;
		static FunctionDefinition<Value*> const* const s_fdGraphic;
		static FunctionDefinition<int> const* const s_fdInt;
		static FunctionDefinition<RECT> const* const s_fdRect;
		static FunctionDefinition<Value*> const* s_fdString;
	
	private:
		void SetParseState(DUI_PARSE_STATE);
	};

	class UILIB_API DUIFactory
	{
	public:
		DUIFactory(HWND);
		~DUIFactory(void);
		DUIFactory & operator=(DUIFactory const &);
		long CreateParser(void);
		DUIXmlParser * DetachParser(void);
		DUIXmlParser * GetParser(void);
		long LoadFromBuffer(UCString, unsigned int, UCString, Element *, unsigned long *, Element * *);
		long LoadFromFile(UCString, UCString, Element *, unsigned long *, Element * *);
		long LoadFromResource(HINSTANCE, UCString, UCString, Element *, unsigned long *, Element * *, UCString);
		void __cdecl SetError(UCString, ...);

	private:
		static void __stdcall s_XMLParseError(UCString, UCString, int, void *);
		void ClearParser(void);
	};

}