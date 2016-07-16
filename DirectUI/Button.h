#pragma once
#include "types.h"

namespace DirectUI
{
	class UILIB_API Button : public Element
	{
	public:
		Button(const Button&);
		Button();
		virtual ~Button();
		Button & operator=(const Button&);

		long Initialize(unsigned int, Element*, unsigned long*);
		static HRESULT WINAPI Create(unsigned int, Element*, unsigned long*, Element**);
		static HRESULT WINAPI Create(Element*, unsigned long*, Element**);

		static UID Click();
		static UID Context();
		//0
		virtual void OnPropertyChanged(const PropertyInfo*, int, Value*, Value*);
		//1
		virtual void OnInput(InputEvent*);

		//2
		virtual IClassInfo* GetClassInfoW();

		//3
		virtual long DefaultAction();

		bool GetCaptured();
		static IClassInfo* GetClassInfoPtr();
		bool GetPressed();

		virtual bool OnLostDialogFocus(class DialogElement*);
		virtual bool OnReceivedDialogFocus(class DialogElement*);

		static long Register();
		long SetCaptured(bool);
		static void SetClassInfoPtr(IClassInfo*);
		long SetPressed(bool);

		static const PropertyInfo* CapturedProp();
		static const PropertyInfo* PressedProp();

	private:
		static IClassInfo* s_pClassInfo;
	};
}