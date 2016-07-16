#include "parser.h"
#include "DirectUI.h"
namespace DirectUI
{
	DUIXmlParser::DUIXmlParser(const DUIXmlParser &)
	{
	}
	DUIXmlParser::DUIXmlParser()
	{
	}
	DUIXmlParser::~DUIXmlParser()
	{
	}
	DUIXmlParser & DUIXmlParser::operator=(const DUIXmlParser &)
	{
		// TODO: 在此处插入 return 语句
		return*this;
	}
	long DUIXmlParser::Create(DUIXmlParser**, GetSheetCallback, void* sheetParam, ParseErrorCallback, void* parseErrorParam)
	{
		return 0;
	}
	long DUIXmlParser::CreateElement(UCString, Element*, Element*, unsigned long*, Element** out)
	{
		return 0;
	}
	void DUIXmlParser::Destroy()
	{
	}
	void DUIXmlParser::EnableDesignMode()
	{
	}

	GetSheetCallback DUIXmlParser::GetGetSheetCallback()
	{
		return GetSheetCallback();
	}
	HINSTANCE DUIXmlParser::GetHInstance()
	{
		return HINSTANCE();
	}
	HINSTANCE DUIXmlParser::GetResourceHInstance()
	{
		return HINSTANCE();
	}
	long DUIXmlParser::GetSheet(UCString, Value**)
	{
		return 0;
	}
	void* DUIXmlParser::GetSheetContext()
	{
		return nullptr;
	}
	long DUIXmlParser::LookupElement(IXmlReader*, UCString, HINSTANCE, IClassInfo**)
	{
		return 0;
	}
	long DUIXmlParser::LookupElement(LINEINFO, UCString, HINSTANCE, IClassInfo**)
	{
		return 0;
	}
	void DUIXmlParser::SetDefaultHInstance(HINSTANCE)
	{
	}
	void DUIXmlParser::SetGetSheetCallback(GetSheetCallback)
	{
	}
	void DUIXmlParser::SetParseErrorCallback(ParseErrorCallback, void*)
	{
	}
	void DUIXmlParser::SetUnknownAttrCallback(bool(*)(UCString, void*), void*)
	{
	}
	long DUIXmlParser::SetPreprocessedXML(UCString, HINSTANCE, HINSTANCE)
	{
		return 0;
	}
	void DUIXmlParser::SetUnavailableIcon(HICON)
	{
	}
	long DUIXmlParser::SetXML(UCString, HINSTANCE, HINSTANCE)
	{
		return 0;
	}
	long DUIXmlParser::SetXMLFromResource(unsigned int, HINSTANCE, HINSTANCE)
	{
		return 0;
	}
	long DUIXmlParser::SetXMLFromResource(UCString, HINSTANCE, HINSTANCE)
	{
		return 0;
	}
	long DUIXmlParser::UpdateSheets(Element*)
	{
		return 0;
	}
	void DUIXmlParser::_DestroyTables()
	{
	}
	long DUIXmlParser::_InitializeTables()
	{
		return 0;
	}
	long DUIXmlParser::_EnterOnCurrentThread()
	{
		return 0;
	}
	LINEINFO DUIXmlParser::_GetLineInfo(IXmlReader*)
	{
		return LINEINFO();
	}
	long DUIXmlParser::AddRulesToStyleSheet(IXmlReader*, StyleSheet*, UCString, DynamicArray<XMLParserCond, 0>*, DynamicArray<UString, 0>*)
	{
		return 0;
	}
	long DUIXmlParser::CreateLayout(const ParserTools::ExprNode*, long(*)(int, int*, Value**))
	{
		return 0;
	}
	long DUIXmlParser::CreateStyleSheet(IXmlReader*, UCString, StyleSheet**)
	{
		return 0;
	}
	long DUIXmlParser::CreateXmlReader(IXmlReader**)
	{
		return 0;
	}
	long DUIXmlParser::CreateXmlReaderFromHGLOBAL(void*, IXmlReader**)
	{
		return 0;
	}
	long DUIXmlParser::CreateXmlReaderInputWithEncodingName(IStream*, UCString, IUnknown**)
	{
		return 0;
	}
	long DUIXmlParser::GetParserCommon(DUIXmlParser**)
	{
		return 0;
	}
	long DUIXmlParser::GetPropValPairInfo(IXmlReader*, IClassInfo*, UCString, UCString, PropertyInfo**, Value**)
	{
		return 0;
	}
	long DUIXmlParser::GetPropValPairInfo(LINEINFO, IClassInfo*, UCString, UCString, const PropertyInfo**, Value**)
	{
		return 0;
	}
	long DUIXmlParser::GetValueParser(ParserTools::ValueParser**)
	{
		return 0;
	}
	long DUIXmlParser::GetXmlLiteDll(HINSTANCE*)
	{
		return 0;
	}
	long DUIXmlParser::Initialize()
	{
		return 0;
	}
	long DUIXmlParser::InitializeParserFromXmlLiteReader(IXmlReader*)
	{
		return 0;
	}
	bool DUIXmlParser::IsThemeClassName(const ParserTools::ExprNode*)
	{
		return false;
	}
	long DUIXmlParser::MapPropertyEnumValue(const EnumMap*, UCString, int*)
	{
		return 0;
	}
	long DUIXmlParser::MapPropertyNameToPropertyInfo(LINEINFO, IClassInfo*, UCString, const PropertyInfo**)
	{
		return 0;
	}
	long DUIXmlParser::ParseARGBColor(const ParserTools::ExprNode*, unsigned long*)
	{
		return 0;
	}
	long DUIXmlParser::ParseArgs(const ParserTools::ExprNode*, ParsedArg*, unsigned int, const char*)
	{
		return 0;
	}
	long DUIXmlParser::ParseAtomValue(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseBoolValue(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseColor(const ParserTools::ExprNode*, unsigned long*)
	{
		return 0;
	}
	long DUIXmlParser::ParseDFCFill(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseDTBFill(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseFillValue(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseFunction(UCString, const ParserTools::ExprNode*, ParsedArg*, unsigned int, const char*)
	{
		return 0;
	}
	long DUIXmlParser::ParseGTCColor(const ParserTools::ExprNode*, unsigned long*)
	{
		return 0;
	}
	long DUIXmlParser::ParseGTFStr(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseGTMarRect(const ParserTools::ExprNode*, LPRECT)
	{
		return 0;
	}
	long DUIXmlParser::ParseGTMetInt(const ParserTools::ExprNode*, int*)
	{
		return 0;
	}
	long DUIXmlParser::ParseGradientFill(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseGraphicGraphic(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseGraphicHelper(bool, const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseGraphicValue(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseIconGraphic(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseImageGraphic(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseIntValue(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseLayoutValue(const ParserTools::ExprNode*)
	{
		return 0;
	}
	long DUIXmlParser::ParseLibrary(const ParserTools::ExprNode*, HINSTANCE*)
	{
		return 0;
	}
	long DUIXmlParser::ParseLiteral(const ParserTools::ExprNode*, UCString*)
	{
		return 0;
	}
	long DUIXmlParser::ParseLiteralColor(UCString, unsigned long*)
	{
		return 0;
	}
	long DUIXmlParser::ParseLiteralColorInt(UCString, int*)
	{
		return 0;
	}
	long DUIXmlParser::ParseLiteralNumber(UCString, int*)
	{
		return 0;
	}
	long DUIXmlParser::ParseMagnitude(UCString, int*)
	{
		return 0;
	}
	long DUIXmlParser::ParseNumber(const ParserTools::ExprNode*, int*)
	{
		return 0;
	}
	long DUIXmlParser::ParsePointValue(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseQuotedString(const ParserTools::ExprNode*, UCString*)
	{
		return 0;
	}
	long DUIXmlParser::ParseRGBColor(const ParserTools::ExprNode*, unsigned long*)
	{
		return 0;
	}
	long DUIXmlParser::ParseRect(const ParserTools::ExprNode*, LPRECT)
	{
		return 0;
	}
	long DUIXmlParser::ParseRectRect(const ParserTools::ExprNode*, LPRECT)
	{
		return 0;
	}
	long DUIXmlParser::ParseRectValue(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseResStr(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseResid(const ParserTools::ExprNode*, UCString*)
	{
		return 0;
	}
	long DUIXmlParser::ParseSGraphicGraphic(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseSGraphicHelper(bool, const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseSizeValue(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseStringValue(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseStyleSheets(IXmlReader*)
	{
		return 0;
	}
	long DUIXmlParser::ParseSysMetricInt(const ParserTools::ExprNode*, int*)
	{
		return 0;
	}
	long DUIXmlParser::ParseSysMetricStr(const ParserTools::ExprNode*, Value**)
	{
		return 0;
	}
	long DUIXmlParser::ParseTheme(const ParserTools::ExprNode*, void**)
	{
		return 0;
	}
	int DUIXmlParser::QuerySysMetric(int)
	{
		return 0;
	}
	UCString DUIXmlParser::QuerySysMetricStr(int, UString, unsigned int)
	{
		return UString();
	}
	void DUIXmlParser::ReturnValueParser(ParserTools::ValueParser*)
	{
	}
	void DUIXmlParser::SendParseError(UCString, UCString, int, int, long)
	{
	}
	void DUIXmlParser::SendParseError(UCString, UCString, IXmlReader*, long)
	{
	}
	void DUIXmlParser::_LeaveOnCurrentThread()
	{
	}
	long DUIXmlParser::_RecordElementLayout(IXmlReader*, UCString)
	{
		return 0;
	}
	long DUIXmlParser::_RecordElementStyleSheet(UCString, bool)
	{
		return 0;
	}
	long DUIXmlParser::_RecordElementTrees(IXmlReader*)
	{
		return 0;
	}
	long DUIXmlParser::_RecordElementWithChildren(IXmlReader*, bool, UString*)
	{
		return 0;
	}
	long DUIXmlParser::_RecordInstantiateElement(IXmlReader*, UString*)
	{
		return 0;
	}
	long DUIXmlParser::_RecordSetElementProperties(IXmlReader*)
	{
		return 0;
	}
	long DUIXmlParser::_RecordSetValue(IXmlReader*, UCString, UCString)
	{
		return 0;
	}
	void DUIXmlParser::SetParseState(_DUI_PARSE_STATE)
	{
	}
}
