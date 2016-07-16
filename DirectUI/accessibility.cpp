#include "DirectUI.h"

namespace DirectUI
{

	DuiAccessible::DuiAccessible()
	{
	}
	DuiAccessible::~DuiAccessible()
	{
	}
	void DuiAccessible::Initialize(Element *)
	{
	}
	HRESULT DuiAccessible::Create(Element *, DuiAccessible **)
	{
		return E_NOTIMPL;
	}
	Element * DuiAccessible::GetAccessibleParent(Element *)
	{
		return nullptr;
	}
	HRESULT DuiAccessible::AccNavigate(Element *, long, Element **)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::Disconnect(void)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::QueryInterface(REFIID riid, void ** ppvObject)
	{
		return E_NOTIMPL;
	}
	ULONG DuiAccessible::AddRef()
	{
		return 0;
	}
	ULONG DuiAccessible::Release()
	{
		return 0;
	}
	HRESULT DuiAccessible::GetTypeInfoCount(UINT * pctinfo)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::GetTypeInfo(UINT iTInfo, LCID lcid, ITypeInfo ** ppTInfo)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::GetIDsOfNames(REFIID riid, LPOLESTR * rgszNames, UINT cNames, LCID lcid, DISPID * rgDispId)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::Invoke(DISPID dispIdMember, REFIID riid, LCID lcid, WORD wFlags, DISPPARAMS * pDispParams, VARIANT * pVarResult, EXCEPINFO * pExcepInfo, UINT * puArgErr)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::GetIdentityString(DWORD dwIDChild, BYTE ** ppIDString, DWORD * pdwIDStringLen)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accParent(IDispatch **)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accChildCount(long *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accChild(VARIANT, IDispatch **)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accName(VARIANT, BSTR *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accValue(VARIANT, BSTR *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accDescription(VARIANT, BSTR *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accRole(VARIANT, VARIANT *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accState(VARIANT, VARIANT *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accHelp(VARIANT, BSTR *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accHelpTopic(BSTR *, VARIANT, long *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accKeyboardShortcut(VARIANT, BSTR *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accFocus(VARIANT *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accSelection(VARIANT *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::get_accDefaultAction(VARIANT, BSTR *)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::accSelect(long flagsSelect, VARIANT varID)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::accLocation(long * pxLeft, long * pyTop, long * pcxWidth, long * pcyHeight, VARIANT varID)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::accNavigate(long navDir, VARIANT varStart, VARIANT * pvarEnd)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::accHitTest(long xLeft, long yTop, VARIANT * pvarID)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::accDoDefaultAction(VARIANT varID)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::put_accName(VARIANT varID, BSTR pszValue)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::put_accValue(VARIANT varID, BSTR pszValue)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::Clone(IEnumVARIANT ** ppEnum)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::Next(unsigned long celt, VARIANT * rgVar, unsigned long * pCeltFetched)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::Reset()
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::Skip(unsigned long celt)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::GetWindow(HWND * phwnd)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::ContextSensitiveHelp(BOOL fEnterMode)
	{
		return E_NOTIMPL;
	}
	HRESULT DuiAccessible::QueryService(REFGUID guidService, REFIID riid, void ** ppv)
	{
		return E_NOTIMPL;
	}
	long DuiAccessible::GetAccName(VARIANT, int, unsigned short **)
	{
		return 0;
	}
	long DuiAccessible::GetAccNameFromContent(unsigned short **)
	{
		return 0;
	}
	long DuiAccessible::GetDispatchFromElement(Element *, IDispatch **)
	{
		return 0;
	}
}
