#pragma once

namespace DirectUI
{
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

	class UILIB_API CritSecLock
	{
	public:
		CritSecLock(CRITICAL_SECTION*);
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

	class Surface
	{
	public:

		enum EType
		{

		};

		Surface(Surface const &);
		Surface(void);
		virtual ~Surface(void);
		Surface & operator=(Surface const &);

		static enum EType __stdcall GetSurfaceType(unsigned int);
		static unsigned int __stdcall GetSurfaceType(enum EType);
	};

	class UILIB_API DCSurface
	{
	public:
		DCSurface(DCSurface const &);
		DCSurface(HDC);
		virtual ~DCSurface(void);
		DCSurface & operator=(DCSurface const &);

		HDC GetHDC(void);
		virtual Surface::EType GetType(void) const;
	};

}
