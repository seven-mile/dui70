#pragma once

namespace DirectUI
{
	class UILIB_API HWNDElementProvider
		: public ElementProvider
	{
	public:
		HWNDElementProvider(void);
		virtual ~HWNDElementProvider(void);

		static long __stdcall Create(HWNDElement *, InvokeHelper *, HWNDElementProvider * *);

		virtual unsigned long __stdcall AddRef(void);
		virtual long __stdcall QueryInterface(struct _GUID const &, void * *);
		virtual unsigned long __stdcall Release(void);

		virtual ProviderProxyCall __stdcall GetProxyCreator(void);

		//1
		virtual long __stdcall ElementProviderFromPoint(double, double, IRawElementProviderFragment * *);
		//2
		virtual long __stdcall GetFocus(IRawElementProviderFragment * *);

	protected:
		virtual long Init(HWNDElement *, InvokeHelper *);

	};

	//此类存在问题，看虚表3有个，但是导出只有2个，怪异……
	class UILIB_API HWNDElementProxy
	{
	public:
		HWNDElementProxy(HWNDElementProxy const &);
		HWNDElementProxy(void);
		HWNDElementProxy & operator=(HWNDElementProxy const &);

		static HWNDElementProxy * __stdcall Create(HWNDElement *);
		virtual long DoMethod(int, char *);
		virtual void Init(HWNDElement *);

	protected:
		long ElementFromPoint(double, double, IRawElementProviderFragment * *);
		long GetFocus(IRawElementProviderFragment * *);

	};
}