#include "Button.h"

namespace DirectUI
{
	Button::Button(const Button &)
	{
	}
	Button::Button()
	{
	}
	Button::~Button()
	{
	}
	Button & Button::operator=(const Button &)
	{
		// TODO: 在此处插入 return 语句
		return *this;
	}
	long Button::Initialize(unsigned int, Element *, unsigned long *)
	{
		return 0;
	}
	long Button::Create(unsigned int, Element *, unsigned long *, Element **)
	{
		return 0;
	}
	long Button::Create(Element *, unsigned long *, Element **)
	{
		return 0;
	}
	UID Button::Click()
	{
		return UID();
	}
	UID Button::Context()
	{
		return UID();
	}
	void Button::OnPropertyChanged(const PropertyInfo *, int, Value *, Value *)
	{
	}
	void Button::OnInput(InputEvent *)
	{
	}
	IClassInfo * Button::GetClassInfoW()
	{
		return nullptr;
	}
	long Button::DefaultAction()
	{
		return 0;
	}
	bool Button::GetCaptured()
	{
		return false;
	}
	IClassInfo * Button::GetClassInfoPtr()
	{
		return nullptr;
	}
	bool Button::GetPressed()
	{
		return false;
	}
	bool Button::OnLostDialogFocus(DialogElement *)
	{
		return false;
	}
	bool Button::OnReceivedDialogFocus(DialogElement *)
	{
		return false;
	}
	long Button::Register()
	{
		return 0;
	}
	long Button::SetCaptured(bool)
	{
		return 0;
	}
	void Button::SetClassInfoPtr(IClassInfo *)
	{
	}
	long Button::SetPressed(bool)
	{
		return 0;
	}
	const PropertyInfo * Button::CapturedProp()
	{
		return nullptr;
	}
	const PropertyInfo * Button::PressedProp()
	{
		return nullptr;
	}
}