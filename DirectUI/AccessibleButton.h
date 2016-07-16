#pragma once

namespace DirectUI
{
	class UILIB_API AccessibleButton : public Button
	{
	public:
		AccessibleButton(const AccessibleButton&);
		AccessibleButton();
		
		virtual ~AccessibleButton();
		AccessibleButton& operator=(const AccessibleButton&);

		static HRESULT WINAPI Create(Element*, unsigned long*, Element**);
		static IClassInfo* WINAPI GetClassInfoPtr();
		//Buttonº¯ÊýÖØÐ´
		//0
		virtual void OnPropertyChanged(const PropertyInfo*, int, Value*, Value*);
		//1
		virtual IClassInfo* GetClassInfoW();

		long Initialize(Element*, unsigned long*);

		void Recalc();
		static HRESULT WINAPI Register();
		static void WINAPI SetClassInfoPtr(IClassInfo*);

		// member types
		struct ACCESSIBLEROLE
		{
			// see http://msdn.microsoft.com/en-us/library/system.windows.forms.accessiblerole.aspx
			ACCESSIBLEROLE& operator=(const ACCESSIBLEROLE&);
		};

	private:
		static ACCESSIBLEROLE const* const c_rgar;
		static IClassInfo* s_pClassInfo;
		static const ACCESSIBLEROLE* FindAccessibleRole(int);
	};

}