// Copyright Epic Games, Inc. All Rights Reserved.

#include "MCPServer.h"
#include "Engine/Engine.h"
#include "HAL/PlatformFilemanager.h"

#define LOCTEXT_NAMESPACE "FMCPServerModule"

DEFINE_LOG_CATEGORY(LogMCPServer);

// Static member variable definitions
TSharedPtr<FMCPLogCaptureDevice> FMCPServerModule::LogCaptureDevice = nullptr;
bool FMCPServerModule::bLogCaptureEnabled = false;
IConsoleVariable* FMCPServerModule::LogCaptureConsoleVariable = nullptr;
IConsoleCommand* FMCPServerModule::PrintCapturedLogsConsoleCommand = nullptr;

// FMCPLogCaptureDevice implementation
FMCPLogCaptureDevice::FMCPLogCaptureDevice()
	: bEnabled(false)
{
}

FMCPLogCaptureDevice::~FMCPLogCaptureDevice()
{
	// Ensure removal from global logging system during destruction
	if (GLog && bEnabled)
	{
		GLog->RemoveOutputDevice(this);
	}
}

void FMCPLogCaptureDevice::Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const FName& Category)
{
	if (!bEnabled)
	{
		return;
	}

	FScopeLock Lock(&LogMutex);
	
	// Format log message
	FString LogMessage = FString::Printf(TEXT("[%s] %s: %s\n"), 
		*Category.ToString(), 
		ToString(Verbosity), 
		V);
	
	CapturedLogs += LogMessage;
}

void FMCPLogCaptureDevice::Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const FName& Category, const double Time)
{
	if (!bEnabled)
	{
		return;
	}

	FScopeLock Lock(&LogMutex);
	
	// Format timestamped log message
	// FDateTime DateTime = FDateTime::FromUnixTimestamp(Time);
	// FString TimeString = DateTime.ToString(TEXT("%Y-%m-%d %H:%M:%S"));
	
	FString LogMessage = FString::Printf(TEXT("[%s] %s: %s\n"), 
		*Category.ToString(), 
		ToString(Verbosity), 
		V);
	
	CapturedLogs += LogMessage;
}

FString FMCPLogCaptureDevice::GetCapturedLogs() const
{
	FScopeLock Lock(&LogMutex);
	return CapturedLogs;
}

void FMCPLogCaptureDevice::ClearCapturedLogs()
{
	FScopeLock Lock(&LogMutex);
	CapturedLogs.Empty();
}

void FMCPLogCaptureDevice::SetEnabled(bool bInEnabled)
{
	FScopeLock Lock(&LogMutex);
	
	if (bEnabled != bInEnabled)
	{
		bEnabled = bInEnabled;
		
		if (GLog)
		{
			if (bEnabled)
			{
				// 添加到全局日志系统
				GLog->AddOutputDevice(this);
			}
			else
			{
				// 从全局日志系统移除
				GLog->RemoveOutputDevice(this);
			}
		}
	}
}

bool FMCPLogCaptureDevice::IsEnabled() const
{
	FScopeLock Lock(&LogMutex);
	return bEnabled;
}

// FMCPServerModule 实现
void FMCPServerModule::StartupModule()
{
	// 创建日志捕获设备
	LogCaptureDevice = MakeShared<FMCPLogCaptureDevice>();
	
	// 注册控制台变量
	LogCaptureConsoleVariable = IConsoleManager::Get().RegisterConsoleVariable(
		TEXT("MCP.LogCapture"),
		0,
		TEXT("0: disable log capture, 1: enable log capture"),
		ECVF_Default
	);
	LogCaptureConsoleVariable->SetOnChangedCallback(FConsoleVariableDelegate::CreateStatic(&FMCPServerModule::OnLogCaptureConsoleVariableChanged));
	
	// 注册控制台命令
	PrintCapturedLogsConsoleCommand = IConsoleManager::Get().RegisterConsoleCommand(
		TEXT("MCP.PrintCapturedLogs"),
		TEXT("print all captured logs to console"),
		FConsoleCommandWithArgsDelegate::CreateStatic(&FMCPServerModule::PrintCapturedLogsCommand),
		ECVF_Default
	);
	
	UE_LOG(LogMCPServer, Log, TEXT("MCP Server module started, log capture functionality available"));
}

void FMCPServerModule::ShutdownModule()
{
	// 注销控制台变量
	if (LogCaptureConsoleVariable)
	{
		IConsoleManager::Get().UnregisterConsoleObject(LogCaptureConsoleVariable);
		LogCaptureConsoleVariable = nullptr;
	}
	
	// 注销控制台命令
	if (PrintCapturedLogsConsoleCommand)
	{
		IConsoleManager::Get().UnregisterConsoleObject(PrintCapturedLogsConsoleCommand);
		PrintCapturedLogsConsoleCommand = nullptr;
	}
	
	// 清理日志捕获设备
	if (LogCaptureDevice.IsValid())
	{
		LogCaptureDevice->SetEnabled(false);
		LogCaptureDevice.Reset();
	}
	
	bLogCaptureEnabled = false;
	
	UE_LOG(LogMCPServer, Log, TEXT("MCP Server module shutdown"));
}

void FMCPServerModule::EnableLogCapture(bool bEnable)
{
	if (LogCaptureDevice.IsValid())
	{
		if (bEnable)
		{
			UE_LOG(LogMCPServer, Verbose, TEXT("=== log capture enable ==="));
		}
		else
		{
			UE_LOG(LogMCPServer, Verbose, TEXT("=== log capture disable ==="));
		}
		LogCaptureDevice->SetEnabled(bEnable);
		bLogCaptureEnabled = bEnable;
		

	}
	else
	{
		UE_LOG(LogMCPServer, Error, TEXT("Log capture device not initialized"));
	}
}

void FMCPServerModule::DisableLogCapture()
{
	EnableLogCapture(false);
}

bool FMCPServerModule::IsLogCaptureEnabled()
{
	return bLogCaptureEnabled && LogCaptureDevice.IsValid() && LogCaptureDevice->IsEnabled();
}

FString FMCPServerModule::GetCapturedLogs()
{
	if (LogCaptureDevice.IsValid())
	{
		return LogCaptureDevice->GetCapturedLogs();
	}
	
	return FString(TEXT("Log capture device not initialized"));
}

void FMCPServerModule::ClearCapturedLogs()
{
	if (LogCaptureDevice.IsValid())
	{
		LogCaptureDevice->ClearCapturedLogs();
		UE_LOG(LogMCPServer, Log, TEXT("Captured logs cleared"));
	}
}

void FMCPServerModule::OnLogCaptureConsoleVariableChanged(IConsoleVariable* Var)
{
	if (Var)
	{
		int32 Value = Var->GetInt();
		bool bShouldEnable = (Value != 0);
		
		UE_LOG(LogMCPServer, Verbose, TEXT("MCP.LogCapture changed to: %d"), Value);
		
		// 通过现有的接口启用或禁用日志捕获
		EnableLogCapture(bShouldEnable);
	}
}

void FMCPServerModule::PrintCapturedLogsCommand(const TArray<FString>& Args)
{
	if (!LogCaptureDevice.IsValid())
	{
		UE_LOG(LogMCPServer, Error, TEXT("Log capture device not initialized"));
		return;
	}
	
	FString CapturedLogs = LogCaptureDevice->GetCapturedLogs();
	
	if (CapturedLogs.IsEmpty())
	{
		UE_LOG(LogMCPServer, Verbose, TEXT("=== No logs currently captured ==="));
		return;
	}
	
	// 计算日志行数
	TArray<FString> LogLines;
	CapturedLogs.ParseIntoArray(LogLines, TEXT("\n"));
	int32 LogCount = LogLines.Num();
	
	UE_LOG(LogMCPServer, Verbose, TEXT("=== Begin printing captured logs (%d lines total) ==="), LogCount);
	
	// 逐行打印捕获的日志
	for (int32 i = 0; i < LogLines.Num(); ++i)
	{
		const FString& Line = LogLines[i];
		if (!Line.IsEmpty())
		{
			// 使用不同的日志级别来区分捕获的日志内容
			UE_LOG(LogMCPServer, Display, TEXT("%s"), *Line);
		}
	}
	
	UE_LOG(LogMCPServer, Verbose, TEXT("=== Log printing completed ==="));
	
	// 如果有参数 "clear"，则打印后清空日志
	if (Args.Num() > 0 && Args[0].ToLower() == TEXT("clear"))
	{
		LogCaptureDevice->ClearCapturedLogs();
		UE_LOG(LogMCPServer, Verbose, TEXT("captured logs cleared"));
	}
}

#undef LOCTEXT_NAMESPACE
	
IMPLEMENT_MODULE(FMCPServerModule, MCPServer)