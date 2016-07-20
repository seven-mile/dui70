#pragma once

namespace DirectUI
{
	class UILIB_API EventManager
	{
	public:
		EventManager & operator=(EventManager const &);

		static unsigned long __stdcall AddRectangleChange(Element *, bool, bool);
		static unsigned long __stdcall AdviseEventAdded(LPCRITICAL_SECTION lpCriticalSection, SAFEARRAY *);
		static unsigned long __stdcall AdviseEventRemoved(int, SAFEARRAY *);
		static void __stdcall Close();
		static void __stdcall DestroyListener(Element *);
		static unsigned long __stdcall EndDefer(Element *);
		static unsigned long __stdcall EventListener(Element *, Event *);
		static bool __stdcall FWantAnyEvent(Element *);
		static unsigned long __stdcall FireStructureChangedEvent(Element *, StructureChangeType);
		static unsigned long __stdcall GetBool(VARIANT *, Value *);
		static void __stdcall GetExpandCollapseState(VARIANT *);
		static unsigned long __stdcall GetInt(VARIANT *, Value *);
		static unsigned long __stdcall GetString(VARIANT *, Value *);
		static void __stdcall GetToggleState(VARIANT *);
		static unsigned long __stdcall HandleAccChange(Element *, IRawElementProviderSimple *, Value *, Value *);
		static unsigned long __stdcall HandleAccDesc(Element *, IRawElementProviderSimple *, Value *, Value *);
		static unsigned long __stdcall HandleAccPatternChange(Element *, IRawElementProviderSimple *, unsigned int, unsigned int, int, VARIANT *, VARIANT *, void(__stdcall *)(VARIANT *));
		static unsigned long __stdcall HandleAccRoleEvent(IRawElementProviderSimple *, Value *, Value *);
		static unsigned long __stdcall HandleAccStateChange(IRawElementProviderSimple *, unsigned int, unsigned int, int, VARIANT *, VARIANT *);
		static unsigned long __stdcall HandleBoolProp(Element *, bool (__stdcall *)(Element *), IRawElementProviderSimple *, int, Value *, Value *);
		static unsigned long __stdcall HandleChildrenEvent(Element *, Value *, Value *);
		static unsigned long __stdcall HandleRangeValue(Element *, IRawElementProviderSimple *, Value *, Value *);
		static unsigned long __stdcall HandleScrollPos(Element *, IRawElementProviderSimple *, Value *, Value *);
		static unsigned long __stdcall HandleSelectedChange(IRawElementProviderSimple *, Value *);
		static unsigned long __stdcall HandleStringProp(IRawElementProviderSimple *, int, Value *, Value *);
		static unsigned long __stdcall HandleVisibilityChange(Element *, unsigned int);
		static unsigned long __stdcall Init();
		static unsigned long __stdcall OnToolTip(Element *, unsigned unsigned long);
		static unsigned long __stdcall PropertyChangingListener(Element *, const PropertyInfo *, bool *);
		static unsigned long __stdcall PropertyListener(Element *, const PropertyInfo *, int, Value *, Value *);
		static unsigned long __stdcall RaiseChildRemovedEvent(const ElementRuntimeId *, Element *);
		static unsigned long __stdcall RaiseGeometryEventWorker(RectangleChange *, bool, bool, bool, bool);
		static unsigned long __stdcall RaiseGeometryEvents();
		static unsigned long __stdcall RaiseStructureChangedEvent(Element *, StructureChangeType);
		static unsigned long __stdcall RaiseStructureEvents();
		static unsigned long __stdcall RaiseVisibilityEvents();
		static bool __stdcall WantEvent(Schema::Event);
		static bool __stdcall WantEvent(Schema::Event, int);
		static bool __stdcall WantPropertyEvent(int);
	};
}