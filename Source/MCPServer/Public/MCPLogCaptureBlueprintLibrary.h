// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MCPLogCaptureBlueprintLibrary.generated.h"

/**
 * 蓝图函数库，用于在蓝图中控制 MCP 日志捕获功能
 */
UCLASS()
class UMCPLogCaptureBlueprintLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * 启用日志捕获功能
	 * @param bEnable 是否启用日志捕获
	 */
	UFUNCTION(BlueprintCallable, Category = "MCP|Log Capture", meta = (DisplayName = "Enable MCP Log Capture"))
	static void EnableLogCapture(bool bEnable = true);

	/**
	 * 禁用日志捕获功能
	 */
	UFUNCTION(BlueprintCallable, Category = "MCP|Log Capture", meta = (DisplayName = "Disable MCP Log Capture"))
	static void DisableLogCapture();

	/**
	 * 检查日志捕获是否已启用
	 * @return 如果日志捕获已启用返回 true，否则返回 false
	 */
	UFUNCTION(BlueprintPure, Category = "MCP|Log Capture", meta = (DisplayName = "Is MCP Log Capture Enabled"))
	static bool IsLogCaptureEnabled();

	/**
	 * 获取当前捕获的所有日志内容
	 * @return 包含所有捕获日志的字符串
	 */
	UFUNCTION(BlueprintPure, Category = "MCP|Log Capture", meta = (DisplayName = "Get Captured Logs"))
	static FString GetCapturedLogs();

	/**
	 * 清空当前捕获的所有日志
	 */
	UFUNCTION(BlueprintCallable, Category = "MCP|Log Capture", meta = (DisplayName = "Clear Captured Logs"))
	static void ClearCapturedLogs();

	/**
	 * 获取捕获的日志行数
	 * @return 捕获的日志行数
	 */
	UFUNCTION(BlueprintPure, Category = "MCP|Log Capture", meta = (DisplayName = "Get Captured Log Count"))
	static int32 GetCapturedLogCount();

	/**
	 * 检查是否有捕获到日志
	 * @return 如果有捕获到日志返回 true，否则返回 false
	 */
	UFUNCTION(BlueprintPure, Category = "MCP|Log Capture", meta = (DisplayName = "Has Captured Logs"))
	static bool HasCapturedLogs();

	/**
	 * 打印捕获的日志到控制台（等同于控制台命令 MCP.PrintCapturedLogs）
	 * @param bClearAfterPrint 打印后是否清空日志
	 */
	UFUNCTION(BlueprintCallable, Category = "MCP|Log Capture", meta = (DisplayName = "Print Captured Logs to Console"))
	static void PrintCapturedLogsToConsole(bool bClearAfterPrint = false);
};
