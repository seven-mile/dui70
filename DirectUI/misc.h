#pragma once


namespace DirectUI
{
  // exported for int
	template<typename T>
	class UILIB_API SafeArrayAccessor
	{
	public:
		SafeArrayAccessor();
		~SafeArrayAccessor();
		SafeArrayAccessor(const SafeArrayAccessor&) = delete;
		SafeArrayAccessor& operator=(const SafeArrayAccessor&) = delete;

		operator T*();
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

	class UILIB_API Expression
	{
	public:
		Expression() = delete;
		Expression(const Expression&) = delete;
		~Expression() = delete;

		Expression & operator=(Expression const &);
		void Destroy(void);
	};


	
	

	/*class UID
	{
	public:
	};*/

	class UILIB_API Surface
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

		virtual void T1() = 0;
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

	struct Event
	{
	};

	struct InputEvent
	{

	};

	struct RectangleChange
	{

	};

	struct ElementRuntimeId
	{

	};

	class UILIB_API ResourceModuleHandles
	{
	public:
		ResourceModuleHandles(void);
		~ResourceModuleHandles(void);
		ResourceModuleHandles & operator=(ResourceModuleHandles const &);
		long GetHandle(unsigned short const *, HINSTANCE *);
	private:
		static long volatile g_cRefCount;

	};

	template<class T>
	class UiaArray
	{
	public:

	};

	class DeferCycle
	{

	};

}
