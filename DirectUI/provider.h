#pragma once

namespace DirectUI
{
	//此类的声明很可能错误
	class UILIB_API ElementProvider
		: public RefcountBase
		, public IRawElementProviderSimple
		, public IRawElementProviderFragment
		, public IRawElementProviderAdviseEvents
	{
	public:
		ElementProvider();
		virtual ~ElementProvider();
		
		static long WINAPI Create(Element*, class  InvokeHelper*, ElementProvider**out);

		long DoInvokeArgs(int, class ProviderProxy* (__cdecl*)(Element*), char*);
		const Element* GetElementKey();
		void TossElement();
		void TossPatternProvider(Schema::Pattern);


		//IUnknown
		virtual unsigned long WINAPI AddRef();
		virtual unsigned long WINAPI Release();
		virtual long WINAPI QueryInterface(const GUID&, void**);

		//IRawElementProviderSimple
		virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_ProviderOptions(
			/* [retval][out] */ __RPC__out enum ProviderOptions *pRetVal);

		virtual HRESULT STDMETHODCALLTYPE GetPatternProvider(
			/* [in] */ PATTERNID patternId,
			/* [retval][out] */ __RPC__deref_out_opt IUnknown **pRetVal);

		virtual HRESULT STDMETHODCALLTYPE GetPropertyValue(
			/* [in] */ PROPERTYID propertyId,
			/* [retval][out] */ __RPC__out VARIANT *pRetVal);

		virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_HostRawElementProvider(
			/* [retval][out] */ __RPC__deref_out_opt IRawElementProviderSimple **pRetVal);

		//IRawElementProviderFragment
		virtual HRESULT STDMETHODCALLTYPE Navigate(
			/* [in] */ enum NavigateDirection direction,
			/* [retval][out] */ __RPC__deref_out_opt IRawElementProviderFragment **pRetVal);

		virtual HRESULT STDMETHODCALLTYPE GetRuntimeId(
			/* [retval][out] */ __RPC__deref_out_opt SAFEARRAY * *pRetVal);

		virtual HRESULT STDMETHODCALLTYPE get_BoundingRectangle(
			/* [retval][out] */ __RPC__out struct UiaRect *pRetVal);

		virtual HRESULT STDMETHODCALLTYPE GetEmbeddedFragmentRoots(
			/* [retval][out] */ __RPC__deref_out_opt SAFEARRAY * *pRetVal);

		virtual HRESULT STDMETHODCALLTYPE SetFocus(void);

		virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_FragmentRoot(
			/* [retval][out] */ __RPC__deref_out_opt IRawElementProviderFragmentRoot **pRetVal);

		//IRawElementProviderAdviseEvents
		virtual HRESULT STDMETHODCALLTYPE AdviseEventAdded(
			/* [in] */ EVENTID eventId,
			/* [in] */ __RPC__in SAFEARRAY * propertyIDs);

		virtual HRESULT STDMETHODCALLTYPE AdviseEventRemoved(
			/* [in] */ EVENTID eventId,
			/* [in] */ __RPC__in SAFEARRAY * propertyIDs);

		//1 此函数似乎声明不正确
		virtual ProviderProxyCall WINAPI GetProxyCreator();
		//2
		virtual volatile const Element* GetElement();

	protected:
		//3
		virtual long Init(Element*, InvokeHelper*);
		long DoInvoke(int, ...);
	};
	
    template <class X, class Y, int>
    class PatternProvider
		: public RefcountBase
		, public IProvider
		, public Y
    {
        public:
            PatternProvider();
            virtual ~PatternProvider();
            
            static long WINAPI Create(ElementProvider*, IUnknown**);
            virtual void Init(ElementProvider*);
        protected:
            long DoInvoke(int,...);
		private:
			
    };
	
	class UILIB_API XResourceProvider
	{
	public:
		XResourceProvider();
		XResourceProvider( const XResourceProvider& );
		XResourceProvider& operator=( const XResourceProvider& );

		static long Create(XResourceProvider**pOut);
		static long Create(HINSTANCE, UCString, UCString, UCString, XResourceProvider**pOut );
		
		long Initialize(HINSTANCE h, UCString s1, UCString s2, UCString s3);
		
		//1
		virtual long CreateDUICP(HWNDElement*, HWND, HWND, Element**, class DUIXmlParser**);
		//2
		virtual long CreateParserCP(class DUIXmlParser**pOut);
		//3
		virtual void DestroyCP();

	};
}