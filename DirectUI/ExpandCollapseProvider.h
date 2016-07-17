#pragma once

namespace DirectUI
{

	class UILIB_API ExpandCollapseProvider
		: public PatternProvider<ExpandCollapseProvider, IExpandCollapseProvider,1>
	{
	public:
		ExpandCollapseProvider(void);
		virtual ~ExpandCollapseProvider(void);;


		virtual ProviderProxyCall GetProxyCreator(void);


		//IUnknown
		virtual HRESULT STDMETHODCALLTYPE QueryInterface(
			/* [in] */ REFIID riid,
			/* [iid_is][out] */ _COM_Outptr_ void __RPC_FAR *__RPC_FAR *ppvObject);

		virtual ULONG STDMETHODCALLTYPE AddRef(void);

		virtual ULONG STDMETHODCALLTYPE Release(void);


		//IExpandCollapseProvider
		virtual HRESULT STDMETHODCALLTYPE Expand(void);

		virtual HRESULT STDMETHODCALLTYPE Collapse(void);

		virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_ExpandCollapseState(
			/* [retval][out] */ __RPC__out enum ExpandCollapseState *pRetVal);

	};
}