#pragma once

namespace DirectUI
{
	class IElementListener
	{
	public:
		//0
		virtual void OnListenerAttach(Element*) = 0;
		//1
		virtual void OnListenerDetach(Element*) = 0;
		//2
		virtual bool OnPropertyChanging(const class PropertyInfo*, int, Value*, Value*) = 0;
		//3
		virtual void OnListenedPropertyChanged(Element*, const class PropertyInfo*, int, Value*, Value*) = 0;
		//4
		virtual void OnListenedEvent(Element*,class Event*) = 0;
		//5
		virtual void OnListenedInput(Element*, class InputEvent*) = 0;
	};

	struct IClassInfo
	{
	public:
	};

	class IDataEntry
	{

	};

	typedef class ProviderProxy* (__stdcall * ProviderProxyCall)(class Element *);

	class UILIB_API IProvider
	{
	public:
		IProvider(IProvider const &);
		IProvider(void);
		IProvider & operator=(IProvider const &);

		virtual ProviderProxyCall WINAPI GetProxyCreator(void) = 0;
	};

	class UILIB_API ISBLeak
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

		virtual void T1() = 0;
		virtual void T2() = 0;
		virtual void T3() = 0;
	};

	class UILIB_API IXElementCP
	{
	public:
		IXElementCP(IXElementCP const &);
		IXElementCP(void);
		IXElementCP & operator=(IXElementCP const &);

		virtual void T1() = 0;
	};

	class IDataEngine
	{
	public:
		IDataEngine(IDataEngine const &);
		IDataEngine(void);
		IDataEngine & operator=(IDataEngine const &);

		virtual ~IDataEngine(void);

		virtual void T1() = 0;
		virtual void T2() = 0;
	};

}