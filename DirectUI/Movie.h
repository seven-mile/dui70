#pragma once

namespace DirectUI
{
	// TODO: find a place to put this
	class Movie : public Element
	{
	public:
		Movie(Movie const &);
		Movie();
		virtual ~Movie();

		Movie & operator=(Movie const &);

		static long WINAPI Create(unsigned int, Element*, unsigned long*, Element**);
		static long WINAPI Create(Element*, unsigned long*, Element**);
		static UID WINAPI AdvanceFrame();

		void Forward();
		bool GetAutoStart();
		bool GetAutoStop();
		static IClassInfo* WINAPI GetClassInfoPtr();
		virtual IClassInfo* GetClassInfoW();
		int GetCompositingQuality();
		bool GetDrawOutlines();
		int GetInterpolationMode();
		UCString GetPath(Value**);
		int GetPixelOffsetMode();
		bool GetPlayAllFramesMode();
		bool GetRepeat();
		int GetSmoothingMode();
		HRESULT LoadFromPath(UCString);
		HRESULT LoadFromResource(HINSTANCE, int);
		virtual void OnDestroy();
		virtual void OnEvent(Event*);
		virtual void OnHosted(Element*);
		virtual void Paint(HDC, LPCRECT, LPCRECT, LPRECT, LPRECT);
		void Pause();
		void Play();
		static void WINAPI RawActionProc(struct GMA_ACTIONINFO*);
		static long WINAPI Register();
		void Resume();
		void Rewind();
		long SetAutoStart(bool);
		long SetAutoStop(bool);
		static void WINAPI SetClassInfoPtr(IClassInfo*);
		long SetCompositingQuality(int);
		long SetDrawOutlines(bool);
		long SetInterpolationMode(int);
		long SetPath(UCString);
		long SetPixelOffsetMode(int);
		long SetPlayAllFramesMode(bool);
		long SetRepeat(bool);
		long SetSmoothingMode(int);
		void doAction(struct GMA_ACTIONINFO*);

		static const PropertyInfo* WINAPI AutoStartProp();
		static const PropertyInfo* WINAPI AutoStopProp();
		static const PropertyInfo* WINAPI CompositingQualityProp();
		static const PropertyInfo* WINAPI DrawOutlinesProp();
		static const PropertyInfo* WINAPI InterpolationModeProp();
		static const PropertyInfo* WINAPI PathProp();
		static const PropertyInfo* WINAPI PixelOffsetModeProp();
		static const PropertyInfo* WINAPI PlayAllFramesModeProp();
		static const PropertyInfo* WINAPI RepeatProp();
		static const PropertyInfo* WINAPI SmoothingModeProp();

	private:
		static IClassInfo* s_pClassInfo;
		void advanceFrameActionStart();
		void advanceFrameActionStop();
	};
}