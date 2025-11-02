// Copyright Epic Games, Inc. All Rights Reserved.

#include "MCPServer.h"
#include "Engine/Engine.h"
#include "HAL/PlatformFilemanager.h"
#include "Editor/Transactor.h"

#define LOCTEXT_NAMESPACE "FMCPServerModule"

DEFINE_LOG_CATEGORY(LogMCPServer);
DEFINE_LOG_CATEGORY(LogMCPPropertyListener);

// Static member variable definitions
TSharedPtr<FMCPLogCaptureDevice> FMCPServerModule::LogCaptureDevice = nullptr;
bool FMCPServerModule::bLogCaptureEnabled = false;
IConsoleVariable* FMCPServerModule::LogCaptureConsoleVariable = nullptr;
IConsoleCommand* FMCPServerModule::PrintCapturedLogsConsoleCommand = nullptr;

// 从事务记录中获取原始值
void GetOriginalValueFromTransaction(const FTransaction* Transaction, UObject* Object, const FName& PropertyName, FString& OutOriginalValue)
{
    // 创建临时对象来恢复原始状态
    UObject* TempObject = DuplicateObject(Object, GetTransientPackage());
    if (!TempObject) return;
    
    // 这里需要访问事务的内部记录来恢复原始状态
    // 由于FTransaction的Records是私有的，我们需要使用反射或友元类
    
    FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
    if (Property)
    {
        Property->ExportTextItem_Direct(OutOriginalValue, 
            Property->ContainerPtrToValuePtr<void>(TempObject), 
            nullptr, TempObject, PPF_None);
    }
    
    TempObject->MarkAsGarbage();
}

// 获取属性更改前后的值
void GetPropertyChangeValues(UObject* Object, const FName& PropertyName, FString& OutOldValue, FString& OutNewValue)
{
    if (!Object || !GEditor || !GEditor->Trans) return;
    
    // 获取最近的事务
    const FTransaction* Transaction = GEditor->Trans->GetTransaction(GEditor->Trans->GetQueueLength() - GEditor->Trans->GetUndoCount()-1);
    if (!Transaction) return;
    
    // 查找对象在事务中的记录
    TArray<UObject*> TransactionObjects;
    Transaction->GetTransactionObjects(TransactionObjects);
    
    for (UObject* TransactionObject : TransactionObjects)
    {
        if (TransactionObject == Object)
        {
            // 获取属性的当前值（更改后的值）
            FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
            if (Property)
            {
                Property->ExportTextItem_Direct(OutNewValue, 
                    Property->ContainerPtrToValuePtr<void>(Object), 
                    nullptr, Object, PPF_None);
                
                // 通过事务差异获取原始值
                FTransactionDiff TransactionDiff = Transaction->GenerateDiff();
                for (const auto& DiffPair : TransactionDiff.DiffMap)
                {
                    TSharedPtr<FTransactionObjectEvent> Event = DiffPair.Value;
                    if (Event && Event->GetChangedProperties().Contains(PropertyName))
                    {
                        // 这里需要从事务记录中恢复原始值
                        GetOriginalValueFromTransaction(Transaction, Object, PropertyName, OutOldValue);
                        return;
                    }
                }
            }
            break;
        }
    }
}


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
	
	LogCaptureConsoleVariable = IConsoleManager::Get().RegisterConsoleVariable(
		TEXT("MCP.LogCapture"),
		0,
		TEXT("0: disable log capture, 1: enable log capture"),
		ECVF_Default
	);
	LogCaptureConsoleVariable->SetOnChangedCallback(FConsoleVariableDelegate::CreateStatic(&FMCPServerModule::OnLogCaptureConsoleVariableChanged));
	
	PrintCapturedLogsConsoleCommand = IConsoleManager::Get().RegisterConsoleCommand(
		TEXT("MCP.PrintCapturedLogs"),
		TEXT("print all captured logs to console"),
		FConsoleCommandWithArgsDelegate::CreateStatic(&FMCPServerModule::PrintCapturedLogsCommand),
		ECVF_Default
	);

	PropertyChangeListenerConsoleVariable =IConsoleManager::Get().RegisterConsoleVariable(
		TEXT("MCP.EnalbeListenProperty"),
		0,
		TEXT("0: disable, 1: enable"),
		ECVF_Default
	);
	
	PropertyChangeListenerConsoleVariable->SetOnChangedCallback(FConsoleVariableDelegate::CreateStatic(&FMCPServerModule::OnPropertyChangeListenerConsoleVariableChanged));
	UE_LOG(LogMCPServer, Log, TEXT("MCP Server module started, log capture functionality available"));
}

void FMCPServerModule::ShutdownModule()
{
	EnableObjectPropertyChangeListener(false);
	if (PropertyChangeListenerConsoleVariable)
	{
		IConsoleManager::Get().UnregisterConsoleObject(PropertyChangeListenerConsoleVariable);
		PropertyChangeListenerConsoleVariable = nullptr;
	}
	
	if (LogCaptureConsoleVariable)
	{
		IConsoleManager::Get().UnregisterConsoleObject(LogCaptureConsoleVariable);
		LogCaptureConsoleVariable = nullptr;
	}
	
	if (PrintCapturedLogsConsoleCommand)
	{
		IConsoleManager::Get().UnregisterConsoleObject(PrintCapturedLogsConsoleCommand);
		PrintCapturedLogsConsoleCommand = nullptr;
	}
	
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

void FMCPServerModule::EnableObjectPropertyChangeListener(bool Enable)
{
	if (Enable)
	{
		if (OnObjectTransactedHandle.IsValid())
		{
			FCoreUObjectDelegates::OnObjectTransacted.Remove(OnObjectTransactedHandle);
		}
		OnObjectTransactedHandle = FCoreUObjectDelegates::OnObjectTransacted.AddLambda([](UObject* Obj, const FTransactionObjectEvent& Event)
		{
			auto PropertiesNames = Event.GetChangedProperties();
			for (auto Name: PropertiesNames)
			{
				FString OldValue;
				FString NewValue;
				GetPropertyChangeValues(Obj,Name,OldValue,NewValue);
				UE_LOG(LogMCPPropertyListener, Log, TEXT("Property:%s,OldValue:%s,NewValue:%s"),*Name.ToString(),*OldValue,*NewValue);
			}
			
		});
	}
	else
	{
		FCoreUObjectDelegates::OnObjectTransacted.Remove(OnObjectTransactedHandle);
		OnObjectTransactedHandle.Reset();
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

void FMCPServerModule::OnPropertyChangeListenerConsoleVariableChanged(IConsoleVariable* Var)
{
	if (Var)
	{
		int32 Value = Var->GetInt();
		bool bShouldEnable = (Value != 0);
		
		if (FMCPServerModule* MCPModule = FModuleManager::GetModulePtr<FMCPServerModule>("MCPServer"))
		{
			MCPModule->EnableObjectPropertyChangeListener(bShouldEnable);
		}
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