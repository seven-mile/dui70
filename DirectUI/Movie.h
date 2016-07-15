#pragma once
#include "types.h"

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

		static long WINAPI Create(unsigned int, Element *, unsigned long *, Element **);
		static long WINAPI Create(Element *, unsigned long *, Element **);
		static UID WINAPI AdvanceFrame();

		void Forward();
		bool GetAutoStart();
		bool GetAutoStop();
		static IClassInfo * WINAPI GetClassInfoPtr();
		virtual IClassInfo * GetClassInfoW();
		int GetCompositingQuality();
		bool GetDrawOutlines();
		int GetInterpolationMode();
		unsigned short const * GetPath(Value **);
		int GetPixelOffsetMode();
		bool GetPlayAllFramesMode();
		bool GetRepeat();
		int GetSmoothingMode();
		HRESULT LoadFromPath(unsigned short const *);
		HRESULT LoadFromResource(HINSTANCE, int);
		virtual void OnDestroy();
		virtual void OnEvent(Event *);
		virtual void OnHosted(Element *);
		virtual void Paint(HDC, LPCRECT, LPCRECT, LPRECT, LPRECT);
		void Pause();
		void Play();
		static void WINAPI RawActionProc(struct GMA_ACTIONINFO *);
		static long WINAPI Register();
		void Resume();
		void Rewind();
		long SetAutoStart(bool);
		long SetAutoStop(bool);
		static void WINAPI SetClassInfoPtr(IClassInfo *);
		long SetCompositingQuality(int);
		long SetDrawOutlines(bool);
		long SetInterpolationMode(int);
		long SetPath(unsigned short const *);
		long SetPixelOffsetMode(int);
		long SetPlayAllFramesMode(bool);
		long SetRepeat(bool);
		long SetSmoothingMode(int);
		void doAction(struct GMA_ACTIONINFO *);

		static PropertyInfo const * WINAPI AutoStartProp();
		static PropertyInfo const * WINAPI AutoStopProp();
		static PropertyInfo const * WINAPI CompositingQualityProp();
		static PropertyInfo const * WINAPI DrawOutlinesProp();
		static PropertyInfo const * WINAPI InterpolationModeProp();
		static PropertyInfo const * WINAPI PathProp();
		static PropertyInfo const * WINAPI PixelOffsetModeProp();
		static PropertyInfo const * WINAPI PlayAllFramesModeProp();
		static PropertyInfo const * WINAPI RepeatProp();
		static PropertyInfo const * WINAPI SmoothingModeProp();

	private:
		static IClassInfo * s_pClassInfo;
		void advanceFrameActionStart();
		void advanceFrameActionStop();
	};
}