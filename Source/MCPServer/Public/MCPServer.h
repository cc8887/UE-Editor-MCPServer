// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"
#include "Misc/OutputDevice.h"
#include "HAL/IConsoleManager.h"

class FMCPTeachingSessionManager;

// 声明 MCP Server 插件专属的日志分类
DECLARE_LOG_CATEGORY_EXTERN(LogMCPServer, Log, All);
DECLARE_LOG_CATEGORY_EXTERN(LogMCPPropertyListener, Log, All);

/**
 * 自定义日志输出设备，用于捕获 UE_LOG 输出到字符串
 */
class FMCPLogCaptureDevice : public FOutputDevice
{
public:
	FMCPLogCaptureDevice();
	virtual ~FMCPLogCaptureDevice();

	// FOutputDevice interface
	virtual void Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const FName& Category) override;
	virtual void Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const FName& Category, const double Time) override;

	// 获取捕获的日志内容
	FString GetCapturedLogs() const;
	
	// 清空捕获的日志
	void ClearCapturedLogs();
	
	// 设置是否启用日志捕获
	void SetEnabled(bool bInEnabled);
	
	// 检查是否启用了日志捕获
	bool IsEnabled() const;

private:
	mutable FCriticalSection LogMutex;
	FString CapturedLogs;
	bool bEnabled;
};

class FMCPServerModule : public IModuleInterface
{
public:

	/** IModuleInterface implementation */
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;

	// 日志捕获控制接口
	static void EnableLogCapture(bool bEnable = true);
	static void DisableLogCapture();
	static bool IsLogCaptureEnabled();
	static FString GetCapturedLogs();
	static void ClearCapturedLogs();

	void EnableObjectPropertyChangeListener(bool Enable);
	static void OnLogCaptureConsoleVariableChanged(IConsoleVariable* Var);
	static void OnPropertyChangeListenerConsoleVariableChanged(IConsoleVariable* Var);
	
	// 控制台命令函数
	static void PrintCapturedLogsCommand(const TArray<FString>& Args);
	static void StartTeachingConsoleCommand(const TArray<FString>& Args);
	static void StopTeachingConsoleCommand(const TArray<FString>& Args);

	TSharedPtr<FMCPTeachingSessionManager> GetTeachingSessionManager() const { return TeachingSessionManager; }
	void StartTeachingSession();
	void StopTeachingSession();
	void RecordTeachingEvent(FName EventName, const FString& Payload);

private:
	static TSharedPtr<FMCPLogCaptureDevice> LogCaptureDevice;
	static bool bLogCaptureEnabled;
	static IConsoleVariable* LogCaptureConsoleVariable;
	static IConsoleCommand* PrintCapturedLogsConsoleCommand;
	IConsoleVariable* PropertyChangeListenerConsoleVariable = nullptr;
	static bool bPropertyChangeListenerEnabled;
	IConsoleCommand* StartTeachingCommand = nullptr;
	IConsoleCommand* StopTeachingCommand = nullptr;

	// 属性值缓存：对象 -> 属性名 -> 属性值
	static TMap<TWeakObjectPtr<UObject>, TMap<FName, FString>> PropertyValueCache;
	static FCriticalSection PropertyCacheMutex;
	
	FDelegateHandle OnObjectTransactedHandle;
	TSharedPtr<FMCPTeachingSessionManager> TeachingSessionManager;
};