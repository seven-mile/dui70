#pragma once

namespace DirectUI
{
	//问号部分无法确定顺序
	class TaskPage
		: public IElementListener
		, public IXProviderCP
	{
	public:
		TaskPage(TaskPage const &);
		TaskPage(void);
		virtual ~TaskPage(void);
		TaskPage & operator=(TaskPage const &);
		operator struct _PSP *(void);

		long DUICreatePropertySheetPage(HINSTANCE);
		HWND GetParentHWND(void);
	
	protected:
		Element * GetElement(void);
		long PropSheet_SendMessage(unsigned int, unsigned int, long);
		
		//IElementListener
		virtual void OnListenerAttach(Element *);
		virtual void OnListenerDetach(Element *);
		virtual bool OnListenedPropertyChanging(Element *, PropertyInfo const *, int, Value *, Value *);
		virtual void OnListenedPropertyChanged(Element *, PropertyInfo const *, int, Value *, Value *);
		virtual void OnListenedEvent(Element *, Event *);
		virtual void OnListenedInput(Element *, InputEvent *);

		//1
		virtual long LoadParser(DUIXmlParser * *);
		//2
		virtual long LoadPage(HWNDElement *, HINSTANCE, Element * *, DUIXmlParser * *);
		//??
		virtual unsigned int GetPageRCID(void);
		virtual unsigned short const * GetPageResID(void);
		//5
		virtual void InitPropSheetPage(PROPSHEETPAGEW *);

		//??
		virtual long OnKillActive(void);
		virtual long OnQueryCancel(void);
		virtual Element * OnQueryInitialFocus(void);
		virtual long OnReset(void);
		virtual long OnSetActive(void);
		virtual long OnWizBack(void);
		virtual long OnWizFinish(void);
		virtual long OnWizNext(void);
		//14
		virtual bool OnMessage(unsigned int, unsigned int, long, long *);

	private:
		static long __stdcall StaticXHostSubclassProc(HWND, unsigned int, unsigned int, long);
		static void __stdcall StaticXmlParserError(unsigned short const *, unsigned short const *, int, void *);

		void FreeComCtl32(void);
		int OnWndMsg(unsigned int, unsigned int, long, long *);
		long LoadComCtl32(void);
		long LoadPage(Element * *, Element *, DUIXmlParser * *);

		//IXProviderCP
		virtual long CreateDUICP(HWNDElement *, HWND, HWND, Element * *, DUIXmlParser * *);
		virtual long CreateParserCP(DUIXmlParser * *);
		virtual void DestroyCP(void);

	};
}