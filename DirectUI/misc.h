#pragma once
#include "types.h"

namespace DirectUI
{
	typedef unsigned short UChar;
	typedef unsigned short* UString;
	typedef const unsigned short* UCString;
    // exported for int
    template<typename>
    class SafeArrayAccessor 
    {
	public:
        SafeArrayAccessor();
        ~SafeArrayAccessor();
        operator typename*();
        long Access(SAFEARRAY *, UChar);
        int Count();
           
	private:
		void*unk1;
		void*unk2;
		void*unk3;
    };

	class CritSecLock
	{
	public:
		CritSecLock(RTL_CRITICAL_SECTION*);
		~CritSecLock();
		CritSecLock & operator=(CritSecLock const &);
		void Unlock();
	};


	template<class T, int>
	class DynamicArray;

	class Expression
	{
	public:

	};

	class StyleSheet
	{
	public:

	};

	
	

	class UID
	{
	public:
	};
}
