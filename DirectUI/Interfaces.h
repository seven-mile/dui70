#pragma once
#include "types.h"

namespace DirectUI
{
	class IElementListener
	{
	public:
		//0
		virtual void OnListenerAttach(Element *) = 0;
		//1
		virtual void OnListenerDetach(Element *) = 0;
		//2
		virtual bool OnPropertyChanging(PropertyInfo const *, int, Value *, Value *) = 0;
		//3
		virtual void OnListenedPropertyChanged(Element *, PropertyInfo const *, int, Value *, Value *) = 0;
		//4
		virtual void OnListenedEvent(Element *, Event *) = 0;
		//5
		virtual void OnListenedInput(Element *, InputEvent *) = 0;
	};

	struct IClassInfo
	{
	public:
	};
	class IDataEngine
	{

	};
	class IDataEntry
	{

	};
	class IProvider
	{

	};
	class ISBLeak
	{

	};
	class IXProviderCP
	{

	};
	class IXElementCP
	{

	};
	struct IXmlReader
	{

	};
	struct IRawElementProviderFragment
	{

	};
	struct IRawElementProviderFragmentRoot
	{

	};
	struct IRawElementProviderSimple
	{

	};
}