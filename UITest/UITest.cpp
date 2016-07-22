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

	auto TT = sizeof(Element);
	TT = sizeof(HWNDElement);


	NativeHWNDHost* pwnd;


	NativeHWNDHost::Create(L"Microsoft DirectUI Test", NULL, NULL, CW_USEDEFAULT, CW_USEDEFAULT, CW_USEDEFAULT, CW_USEDEFAULT, WS_EX_WINDOWEDGE, WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0,&pwnd);
	
	//pwnd->Initialize();


	DUIXmlParser* pParser;

	DUIXmlParser::Create(&pParser, NULL, NULL, NULL, NULL);


	//IDR_UIFILE1
	auto hr=pParser->SetXMLFromResource(IDR_UIFILE1, hInstance,(HINSTANCE)hInstance);

	unsigned long Temp;
	Element* Temp2;

	HWNDElement::Create(pwnd->GetHWND(),true,0,NULL,&Temp,(Element**)&Temp2);

	Element* pWizardMain;
	pParser->CreateElement(L"WizardMain", Temp2,NULL,NULL,(Element**)&pWizardMain);

	pWizardMain->SetVisible(true);
	pWizardMain->EndDefer(Temp);
	pwnd->Host(pWizardMain);


	pwnd->ShowWindow(SW_SHOW);



	StartMessagePump();

	UnInitProcessPriv(NULL);
	return 0;
}