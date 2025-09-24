// Copyright Epic Games, Inc. All Rights Reserved.

#include "MCPServer.h"
#include "Engine/Engine.h"
#include "HAL/PlatformFilemanager.h"

#define LOCTEXT_NAMESPACE "FMCPServerModule"

DEFINE_LOG_CATEGORY(LogMCPServer);

// 静态成员变量定义
TSharedPtr<FMCPLogCaptureDevice> FMCPServerModule::LogCaptureDevice = nullptr;
bool FMCPServerModule::bLogCaptureEnabled = false;
IConsoleVariable* FMCPServerModule::LogCaptureConsoleVariable = nullptr;
IConsoleCommand* FMCPServerModule::PrintCapturedLogsConsoleCommand = nullptr;

// FStringLogOutputDevice 实现
FMCPLogCaptureDevice::FMCPLogCaptureDevice()
	: bEnabled(false)
{
}

FMCPLogCaptureDevice::~FMCPLogCaptureDevice()
{
	// 确保在析构时从全局日志系统中移除
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
	
	// 格式化日志消息
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
	
	// 格式化带时间戳的日志消息
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
				UE_LOG(LogMCPServer, Log, TEXT("日志捕获已启用"));
			}
			else
			{
				// 从全局日志系统移除
				GLog->RemoveOutputDevice(this);
				UE_LOG(LogMCPServer, Log, TEXT("日志捕获已禁用"));
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
		TEXT("0: 禁用日志捕获，1: 启用日志捕获"),
		ECVF_Default
	);
	LogCaptureConsoleVariable->SetOnChangedCallback(FConsoleVariableDelegate::CreateStatic(&FMCPServerModule::OnLogCaptureConsoleVariableChanged));
	
	// 注册控制台命令
	PrintCapturedLogsConsoleCommand = IConsoleManager::Get().RegisterConsoleCommand(
		TEXT("MCP.PrintCapturedLogs"),
		TEXT("打印当前捕获的所有日志内容到控制台"),
		FConsoleCommandWithArgsDelegate::CreateStatic(&FMCPServerModule::PrintCapturedLogsCommand),
		ECVF_Default
	);
	
	UE_LOG(LogMCPServer, Log, TEXT("MCP Server 模块已启动，日志捕获功能可用"));
	UE_LOG(LogMCPServer, Log, TEXT("使用控制台命令:"));
	UE_LOG(LogMCPServer, Log, TEXT("  - 'MCP.LogCapture 1/0' 启用/禁用日志捕获"));
	UE_LOG(LogMCPServer, Log, TEXT("  - 'MCP.PrintCapturedLogs' 打印捕获的日志"));
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
	
	UE_LOG(LogMCPServer, Log, TEXT("MCP Server 模块已关闭"));
}

void FMCPServerModule::EnableLogCapture(bool bEnable)
{
	if (LogCaptureDevice.IsValid())
	{
		LogCaptureDevice->SetEnabled(bEnable);
		bLogCaptureEnabled = bEnable;
		
		if (bEnable)
		{
			UE_LOG(LogMCPServer, Warning, TEXT("=== 日志捕获已启用 ==="));
		}
		else
		{
			UE_LOG(LogMCPServer, Warning, TEXT("=== 日志捕获已禁用 ==="));
		}
	}
	else
	{
		UE_LOG(LogMCPServer, Error, TEXT("日志捕获设备未初始化"));
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
	
	return FString(TEXT("日志捕获设备未初始化"));
}

void FMCPServerModule::ClearCapturedLogs()
{
	if (LogCaptureDevice.IsValid())
	{
		LogCaptureDevice->ClearCapturedLogs();
		UE_LOG(LogMCPServer, Log, TEXT("已清空捕获的日志"));
	}
}

void FMCPServerModule::OnLogCaptureConsoleVariableChanged(IConsoleVariable* Var)
{
	if (Var)
	{
		int32 Value = Var->GetInt();
		bool bShouldEnable = (Value != 0);
		
		UE_LOG(LogMCPServer, Warning, TEXT("控制台变量 MCP.LogCapture 已更改为: %d"), Value);
		
		// 通过现有的接口启用或禁用日志捕获
		EnableLogCapture(bShouldEnable);
	}
}

void FMCPServerModule::PrintCapturedLogsCommand(const TArray<FString>& Args)
{
	if (!LogCaptureDevice.IsValid())
	{
		UE_LOG(LogMCPServer, Error, TEXT("日志捕获设备未初始化"));
		return;
	}
	
	FString CapturedLogs = LogCaptureDevice->GetCapturedLogs();
	
	if (CapturedLogs.IsEmpty())
	{
		UE_LOG(LogMCPServer, Warning, TEXT("=== 当前没有捕获到任何日志 ==="));
		UE_LOG(LogMCPServer, Warning, TEXT("提示: 使用 'MCP.LogCapture 1' 启用日志捕获功能"));
		return;
	}
	
	// 计算日志行数
	TArray<FString> LogLines;
	CapturedLogs.ParseIntoArray(LogLines, TEXT("\n"));
	int32 LogCount = LogLines.Num();
	
	UE_LOG(LogMCPServer, Warning, TEXT("=== 开始打印捕获的日志 (共 %d 行) ==="), LogCount);
	
	// 逐行打印捕获的日志
	for (int32 i = 0; i < LogLines.Num(); ++i)
	{
		const FString& Line = LogLines[i];
		if (!Line.IsEmpty())
		{
			// 使用不同的日志级别来区分捕获的日志内容
			UE_LOG(LogMCPServer, Display, TEXT("[捕获] %s"), *Line);
		}
	}
	
	UE_LOG(LogMCPServer, Warning, TEXT("=== 日志打印完成 ==="));
	
	// 如果有参数 "clear"，则打印后清空日志
	if (Args.Num() > 0 && Args[0].ToLower() == TEXT("clear"))
	{
		LogCaptureDevice->ClearCapturedLogs();
		UE_LOG(LogMCPServer, Warning, TEXT("已清空捕获的日志"));
	}
}

#undef LOCTEXT_NAMESPACE
	
IMPLEMENT_MODULE(FMCPServerModule, MCPServer)