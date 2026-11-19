from mcp.server.fastmcp import FastMCP

# Create the FastMCP server instance
mcp = FastMCP("mcp-documentation-server")

# Register the tool using FastMCP decorator
@mcp.tool()
def get_emails() -> dict:
    """
    This tool returns the emails from the database for the project. 
    It is very useful for figuring out what the project is about.
    """
    ## actual implementation would query a real database here

    return {
        "title": "How to Use MCP Servers",
        "body": "This is a mocked email entry from the database. MCP servers expose tools and resources for AI agents.",
        "source": "mocked_database"
    }


@mcp.tool()
def write_email(recipient: str, subject: str, body: str) -> dict:
    """
    This tool allows you to write an email to a recipient.
    """
    # Here we would normally save the email to a database or send it
    return {
        "status": "success",
        "message": f"Email sent to {recipient} with subject '{subject}' and body '{body}'."
    }