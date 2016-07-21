#pragma once

namespace DirectUI
{
	struct IElementListener
	{
	public:
		//0
		virtual void OnListenerAttach(class Element*) = 0;
		//1
		virtual void OnListenerDetach(class Element*) = 0;
		//2
		virtual bool OnPropertyChanging(const struct PropertyInfo*, int, class Value*, class Value*) = 0;
		//3
		virtual void OnListenedPropertyChanged(class Element*, const struct PropertyInfo*, int, class Value*, class Value*) = 0;
		//4
		virtual void OnListenedEvent(class Element*, struct Event*) = 0;
		//5
		virtual void OnListenedInput(class Element*, struct InputEvent*) = 0;
	};

	struct IClassInfo
	{
	public:
	};

	struct UILIB_API IDataEntry
	{
	public:
		IDataEntry(IDataEntry const &);
		IDataEntry(void);
		virtual ~IDataEntry(void);

		IDataEntry & operator=(IDataEntry const &);
	};

	class DECLSPEC_NOVTABLE IProxy
	{
	public:
		virtual long DoMethod(int, char *) = 0;

	protected:
		virtual void Init(class Element *) = 0;
	};

	class UILIB_API Proxy
	{
	public:
		Proxy(Proxy const &);
		Proxy(void);
		virtual ~Proxy(void);
		Proxy & operator=(Proxy const &);

		static long __stdcall SyncCallback(struct HGADGET__ *, void *, struct EventMsg *);

	protected:
		void Invoke(unsigned int, void *);
		virtual void OnInvoke(unsigned int, void *);

	};

	class UILIB_API ProviderProxy : public IProxy
	{
	public:
		ProviderProxy(ProviderProxy const &);
		ProviderProxy & operator=(ProviderProxy const &);

	protected:
		ProviderProxy(void);
		virtual void Init(class Element *);
	};

	typedef class ProviderProxy* (__stdcall * ProviderProxyCall)(class Element *);

	class UILIB_API IProvider
	{
	public:
		IProvider(IProvider const &);
		IProvider(void);
		IProvider & operator=(IProvider const &);

		virtual ProviderProxyCall GetProxyCreator(void) = 0;
	};

	class UILIB_API RefcountBase
	{
	public:
		RefcountBase();
		RefcountBase(const RefcountBase&) = delete;
		RefcountBase&operator=(const RefcountBase&) = delete;

		virtual ~RefcountBase();

		long AddRef();
		long Release();
	};


	template <class X, class Y, int i>
	class PatternProvider
		: public RefcountBase
		, public IProvider
		//, public Y
	{
	public:
		PatternProvider();
		PatternProvider(const PatternProvider&) = delete;
		PatternProvider& operator=(const PatternProvider&) = delete;
		virtual ~PatternProvider();

		static long WINAPI Create(class ElementProvider*, IUnknown**);
		virtual void Init(class ElementProvider*);
		//IProvider
		virtual ProviderProxyCall GetProxyCreator(void);
	protected:
		long DoInvoke(int, ...);
	private:

	};


	struct UILIB_API ISBLeak
	{
	public:
		ISBLeak(ISBLeak const &);
		ISBLeak(void);
		ISBLeak & operator=(ISBLeak const &);

		virtual void T1() = 0;
		virtual void T2() = 0;
		virtual void T3() = 0;
	};

	class UILIB_API IXProviderCP
	{
	public:
		IXProviderCP(IXProviderCP const &);
		IXProviderCP(void);
		IXProviderCP & operator=(IXProviderCP const &);

		virtual long CreateDUICP(class HWNDElement *, HWND, HWND, class Element * *, class DUIXmlParser * *) = 0;
		virtual long CreateParserCP(class DUIXmlParser * *) = 0;
		virtual void DestroyCP(void) = 0;
	};

	class UILIB_API IXElementCP
	{
	public:
		IXElementCP(IXElementCP const &);
		IXElementCP(void);
		IXElementCP & operator=(IXElementCP const &);

		virtual HWND GetNotificationSinkHWND(void) = 0;
	};

	struct UILIB_API IDataEngine
	{
	public:
		IDataEngine(IDataEngine const &);
		IDataEngine(void);
		IDataEngine & operator=(IDataEngine const &);

		virtual ~IDataEngine(void);

		virtual void T1() = 0;
		virtual void T2() = 0;
	};

	class UILIB_API StyleSheet
	{
	public:
		StyleSheet(StyleSheet const &);
		StyleSheet(void);
		StyleSheet & operator=(StyleSheet const &);

		static long __stdcall Create(StyleSheet * *);

		virtual void T1() = 0;
		virtual void T2() = 0;
		virtual void T3() = 0;
		virtual void T4() = 0;
		virtual void T5() = 0;
		virtual void T6() = 0;
		virtual void T7() = 0;
		virtual void T8() = 0;
	};

}