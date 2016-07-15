#include <Windows.h>
#include "..\DirectUI\DirectUI.h"

#pragma comment(lib,"dui70.lib")
#include "resource.h"

using namespace DirectUI;

class HelloWorldWindow : public NativeHWNDHost
{
public:
	HelloWorldWindow() {
		Initialize(L"Microsoft DirectUI Test", NULL, NULL, CW_USEDEFAULT, CW_USEDEFAULT, CW_USEDEFAULT, CW_USEDEFAULT, WS_EX_WINDOWEDGE, WS_OVERLAPPEDWINDOW| WS_VISIBLE, 0);
	}
};


int CALLBACK WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow)
{
	CoInitializeEx(NULL, 0);

	InitProcessPriv(8, NULL, 1, true);
	InitThread(2);

	RegisterAllControls();
	DUIXmlParser* pParser;

	DUIXmlParser::Create(&pParser, NULL, NULL, NULL, NULL);

	//IDR_UIFILE1
	auto hr=pParser->SetXMLFromResource(IDR_UIFILE1, hInstance,(HINSTANCE)0);

	HelloWorldWindow wnd;
	Button* Temp;

	hr=Button::Create((Element*)NULL,NULL,(Element**)&Temp);

	wnd.ShowWindow(SW_SHOW);



	auto pElement= wnd.GetElement();

	StartMessagePump();

	UnInitProcessPriv(NULL);
	return 0;
}