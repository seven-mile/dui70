#pragma once

namespace DirectUI
{
	
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