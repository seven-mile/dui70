#pragma once
#include "types.h"

namespace DirectUI
{
	typedef unsigned short Char;
	typedef unsigned short* String;

    // exported for int
    template<typename>
    class SafeArrayAccessor 
    {
	public:
        SafeArrayAccessor();
        ~SafeArrayAccessor();
        operator typename*();
        long Access(SAFEARRAY  *, unsigned short);
        int Count();
           
	private:
		void *unk1;
		void *unk2;
		void *unk3;
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
