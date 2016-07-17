#include "DirectUI.h"

namespace DirectUI
{
	RefcountBase::RefcountBase()
	{
	}

	RefcountBase::~RefcountBase()
	{

	}

	unsigned long WINAPI RefcountBase::AddRef()
	{
		return 0;
	}

	unsigned long WINAPI RefcountBase::Release()
	{
		return 0;
	}
}