// Copyright Epic Games, Inc. All Rights Reserved.

#include "MCPLogCaptureBlueprintLibrary.h"
#include "MCPServer.h"

void UMCPLogCaptureBlueprintLibrary::EnableLogCapture(bool bEnable)
{
	FMCPServerModule::EnableLogCapture(bEnable);
}

void UMCPLogCaptureBlueprintLibrary::DisableLogCapture()
{
	FMCPServerModule::DisableLogCapture();
}

bool UMCPLogCaptureBlueprintLibrary::IsLogCaptureEnabled()
{
	return FMCPServerModule::IsLogCaptureEnabled();
}

FString UMCPLogCaptureBlueprintLibrary::GetCapturedLogs()
{
	return FMCPServerModule::GetCapturedLogs();
}

void UMCPLogCaptureBlueprintLibrary::ClearCapturedLogs()
{
	FMCPServerModule::ClearCapturedLogs();
}

int32 UMCPLogCaptureBlueprintLibrary::GetCapturedLogCount()
{
	FString CapturedLogs = FMCPServerModule::GetCapturedLogs();
	
	if (CapturedLogs.IsEmpty())
	{
		return 0;
	}
	
	// 计算日志行数
	TArray<FString> LogLines;
	CapturedLogs.ParseIntoArray(LogLines, TEXT("\n"));
	
	// 过滤掉空行
	int32 ValidLineCount = 0;
	for (const FString& Line : LogLines)
	{
		if (!Line.IsEmpty())
		{
			ValidLineCount++;
		}
	}
	
	return ValidLineCount;
}

bool UMCPLogCaptureBlueprintLibrary::HasCapturedLogs()
{
	FString CapturedLogs = FMCPServerModule::GetCapturedLogs();
	return !CapturedLogs.IsEmpty();
}

void UMCPLogCaptureBlueprintLibrary::PrintCapturedLogsToConsole(bool bClearAfterPrint)
{
	// 构建参数数组
	TArray<FString> Args;
	if (bClearAfterPrint)
	{
		Args.Add(TEXT("clear"));
	}
	
	// 调用控制台命令函数
	FMCPServerModule::PrintCapturedLogsCommand(Args);
}

void UMCPLogCaptureBlueprintLibrary::EnableObjectPropertyChangeListener(bool bEnable)
{
	if (FMCPServerModule* MCPModule = FModuleManager::GetModulePtr<FMCPServerModule>("MCPServer"))
	{
		MCPModule->EnableObjectPropertyChangeListener(bEnable);
	}
}

void UMCPLogCaptureBlueprintLibrary::DisableObjectPropertyChangeListener()
{
	if (FMCPServerModule* MCPModule = FModuleManager::GetModulePtr<FMCPServerModule>("MCPServer"))
	{
		MCPModule->EnableObjectPropertyChangeListener(false);
	}
}


